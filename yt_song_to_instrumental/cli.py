import argparse
import logging
import sys
from typing import NoReturn

import yaml
from pydantic import ValidationError

from yt_song_to_instrumental.config import (
    AppConfig,
    LabelConfig,
    Source,
    YouTubeConfig,
    load_label_config,
)
from yt_song_to_instrumental.constants import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    LABEL_CONFIG_EXAMPLE_FILENAME,
    LABEL_CONFIG_FILENAME,
    VALID_PRIVACY_STATUSES,
)
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, process_url
from yt_song_to_instrumental.preview import PreviewReport, preview_url

logger = logging.getLogger(__name__)


def _fail(message: str) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _load_label_config_or_exit() -> LabelConfig:
    try:
        return load_label_config()
    except FileNotFoundError:
        _fail(
            f"config file '{LABEL_CONFIG_FILENAME}' not found — "
            f"create it from '{LABEL_CONFIG_EXAMPLE_FILENAME}'"
        )
    except (KeyError, ValueError, yaml.YAMLError) as e:
        _fail(f"config file '{LABEL_CONFIG_FILENAME}' is invalid: {e}")


def _youtube_config_or_exit() -> YouTubeConfig:
    try:
        return YouTubeConfig()
    except ValidationError as e:
        _fail(f"missing or invalid YouTube credentials (see .env.example): {e}")


def _list_models() -> None:
    from yt_song_to_instrumental.separator import get_separator

    print("Available separation models:\n")
    for model_id in AVAILABLE_MODELS:
        backend = get_separator(model_id)
        print(f"  {model_id:12s}  {backend.name()}")
        print(f"               GPU required: {'Yes' if backend.gpu_required() else 'No'}")
        print(f"               Min memory:   {backend.min_memory_gb()} GB")
        print()


def _format_upload_date(yyyymmdd: str | None) -> str:
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return "????-??-??"
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _print_preview_report(report: PreviewReport) -> None:
    print(f"\n--- Preview: {report.source_url} ---")
    if report.after_date:
        print(f"after_date: {report.after_date}")
    if report.enumeration_failed:
        print("Could not enumerate the source URL (yt-dlp returned nothing).")
        return
    print(f"Total seen: {report.total_seen}")
    if report.duplicates_dropped:
        print(f"Duplicates dropped (audio preferred): {report.duplicates_dropped}")
    if report.filtered_by_date:
        print(f"Filtered by after_date {report.after_date}: {report.filtered_by_date}")
    print(f"Already in history: {report.skipped_existing}")
    print(f"New videos: {len(report.new_videos)}")

    def _format_track_line(t) -> str:
        date = _format_upload_date(t.upload_date)
        return f"[{date}] {t.projected_video_title}"

    # Sort newest-first per playlist so the user can scan recent uploads at the
    # top and decide whether to tighten label.yml's after_date.
    def _date_key(t) -> str:
        return t.upload_date or "00000000"

    artist_groups: dict[str, list] = {}
    album_groups: dict[str, list] = {}
    for t in report.new_videos:
        for pl in t.projected_artist_playlists:
            artist_groups.setdefault(pl, []).append(t)
        if t.projected_album_playlist:
            album_groups.setdefault(t.projected_album_playlist, []).append(t)

    if artist_groups:
        print(f"\nArtist playlists ({len(artist_groups)}):")
        for name in sorted(artist_groups, key=lambda n: (-len(artist_groups[n]), n)):
            tracks = sorted(artist_groups[name], key=_date_key, reverse=True)
            print(f"\n{name}  ({len(tracks)})")
            for t in tracks:
                print(f"  - {_format_track_line(t)}")
    else:
        print("\nNo artist playlists projected.")

    if album_groups:
        print(f"\nAlbum playlists ({len(album_groups)}):")
        for name in sorted(album_groups):
            tracks = sorted(album_groups[name], key=_date_key, reverse=True)
            print(f"\n{name}  ({len(tracks)})")
            for t in tracks:
                print(f"  - {_format_track_line(t)}")
    else:
        print("\nNo album playlists projected (no album metadata available).")

    unenriched = [t for t in report.new_videos if not t.enriched]
    if unenriched:
        print(f"\nWARNING: {len(unenriched)} videos had no YTMusic match — artist/album may be guessed from uploader/title.")


def _print_pipeline_report(report: PipelineReport) -> None:
    print(f"\n--- Pipeline Report ---")
    print(f"Downloaded:  {report.downloaded}")
    print(f"Separated:   {report.separated}")
    print(f"Uploaded:    {report.uploaded}")
    print(f"Skipped:     {report.skipped}")
    print(f"Failed:      {report.failed}")

    if report.tracks:
        print(f"\nTracks:")
        for t in report.tracks:
            status_str = t.status
            if t.reason:
                status_str += f" ({t.reason})"
            display = t.rendered_title or f"{t.artist} — {t.title}"
            line = f"  [{status_str}] {display}"
            if t.youtube_upload_id:
                line += f" → https://youtu.be/{t.youtube_upload_id}"
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download songs, extract instrumentals, and upload to YouTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", nargs="?", help="YouTube URL (video, playlist, or channel). If omitted, uses `sources:` from label.yml.")
    parser.add_argument("--model", choices=AVAILABLE_MODELS, default=DEFAULT_MODEL, help="Separation model to use")
    parser.add_argument("--skip-upload", action="store_true", help="Separate only, do not upload")
    parser.add_argument("--skip-download", action="store_true", help="Process already-downloaded files only")
    parser.add_argument("--privacy", choices=VALID_PRIVACY_STATUSES, default=None, help="YouTube privacy status")
    parser.add_argument("--dry-run", action="store_true", help="Show projected downloads and playlists without doing anything")
    parser.add_argument("--list-models", action="store_true", help="List available separator models and exit")
    parser.add_argument("--artist", default="", help="Override artist name for all tracks")
    parser.add_argument("--album", default="", help="Override album name for all tracks")
    parser.add_argument("--after-date", default=None, help="Only process videos uploaded after this date (YYYYMMDD). Valid only with an explicit URL, not with sources mode.")
    parser.add_argument("--upload-timeout", type=float, default=None, help="Cap on cumulative retry wait (minutes) for a single upload that hits YouTube's rate limit. Default: no cap, retry indefinitely.")
    parser.add_argument("--sync-channel", action="store_true", help="Update YouTube channel metadata from label.yml")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.list_models:
        _list_models()
        return

    if args.sync_channel:
        label_config = _load_label_config_or_exit()
        yt_config = _youtube_config_or_exit()
        from yt_song_to_instrumental.uploader import authenticate
        from yt_song_to_instrumental.channel import sync_channel_metadata
        service = authenticate(yt_config.client_secrets_file, yt_config.token_file)
        sync_channel_metadata(service, label_config)
        print("Channel metadata synced.")
        return

    app_config = AppConfig()
    label_config = _load_label_config_or_exit()

    if args.url:
        sources_to_run: list[Source] = [Source(url=args.url, after_date=args.after_date)]
    elif label_config.sources:
        if args.after_date:
            parser.error(
                "--after-date is only valid with an explicit URL; sources in label.yml carry per-entry after_date"
            )
        sources_to_run = list(label_config.sources)
    else:
        parser.error("url is required (no sources defined in label.yml)")

    if (args.artist or args.album) and len(sources_to_run) > 1:
        logger.warning(
            "--artist/--album override is being applied to %d sources — usually you want this only for a single URL",
            len(sources_to_run),
        )

    history = HistoryDB(app_config.db_path)

    try:
        if args.dry_run:
            for src in sources_to_run:
                report = preview_url(
                    url=src.url,
                    label_config=label_config,
                    history=history,
                    after_date=src.after_date,
                    model_name=args.model,
                )
                _print_preview_report(report)
            return

        service = None
        if not args.skip_upload:
            yt_config = _youtube_config_or_exit()
            from yt_song_to_instrumental.uploader import authenticate
            service = authenticate(yt_config.client_secrets_file, yt_config.token_file)

        upload_timeout_seconds = args.upload_timeout * 60 if args.upload_timeout else None
        for src in sources_to_run:
            report = process_url(
                url=src.url,
                config=app_config,
                label_config=label_config,
                service=service,
                model_name=args.model,
                privacy=args.privacy,
                skip_upload=args.skip_upload,
                skip_download=args.skip_download,
                artist_override=args.artist,
                album_override=args.album,
                after_date=src.after_date,
                history=history,
                upload_max_wait_seconds=upload_timeout_seconds,
            )
            _print_pipeline_report(report)
    finally:
        history.close()


if __name__ == "__main__":
    main()
