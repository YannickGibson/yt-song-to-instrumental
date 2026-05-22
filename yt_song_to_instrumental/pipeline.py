import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.constants import MODEL_DISPLAY_NAMES
from yt_song_to_instrumental.downloader import DownloadedTrack, download_tracks
from yt_song_to_instrumental.history import DownloadRecord, HistoryDB
from yt_song_to_instrumental.metadata import render_description, render_video_title
from yt_song_to_instrumental.playlists import assign_to_playlists, split_artists
from yt_song_to_instrumental.quality import check_quality
from yt_song_to_instrumental.separator import get_separator
from yt_song_to_instrumental.separator.base import SeparatorBackend
from yt_song_to_instrumental.thumbnail import get_thumbnail_for_track
from yt_song_to_instrumental.uploader import upload_video
from yt_song_to_instrumental.video_render import render_video

logger = logging.getLogger(__name__)


@dataclass
class TrackReport:
    video_id: str
    title: str
    artist: str
    status: str
    reason: str = ""
    rendered_title: str = ""  # the actual title used for the YouTube upload
    youtube_upload_id: str = ""  # ID of the resulting upload on our channel


@dataclass
class PipelineReport:
    downloaded: int = 0
    separated: int = 0
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    tracks: list[TrackReport] = field(default_factory=list)


@dataclass
class _RunContext:
    """Run-invariant values shared by the per-track pipeline stages."""
    service: Any
    history: HistoryDB
    label_config: LabelConfig
    separator: SeparatorBackend
    model: str
    display_name: str
    privacy: str
    tmp_dir: Path
    output_dir: Path
    upload_max_wait_seconds: float | None


def process_url(
    url: str,
    config: AppConfig,
    label_config: LabelConfig,
    service,
    model_name: str | None = None,
    privacy: str | None = None,
    skip_upload: bool = False,
    skip_download: bool = False,
    artist_override: str = "",
    album_override: str = "",
    after_date: str | None = None,
    history: HistoryDB | None = None,
    upload_max_wait_seconds: float | None = None,
) -> PipelineReport:
    report = PipelineReport()
    model = model_name or config.separator_model
    owns_history = history is None
    if history is None:
        history = HistoryDB(config.db_path)

    ctx = _RunContext(
        service=service,
        history=history,
        label_config=label_config,
        separator=get_separator(model),
        model=model,
        display_name=MODEL_DISPLAY_NAMES.get(model, model),
        privacy=privacy or config.default_privacy,
        tmp_dir=Path(config.tmp_dir),
        output_dir=Path(config.output_dir),
        upload_max_wait_seconds=upload_max_wait_seconds,
    )

    if not skip_download:
        logger.info("Downloading tracks from %s", url)
        downloaded = download_tracks(url, history, ctx.tmp_dir, after_date=after_date)
        report.downloaded = len(downloaded)
        logger.info("Downloaded %d new tracks", report.downloaded)

    for track in _select_tracks(history, model, skip_upload):
        artist = artist_override or track.artist
        album = album_override or track.album

        if not _separate_track(track, artist, ctx, report):
            continue

        if skip_upload:
            report.skipped += 1
            report.tracks.append(TrackReport(track.video_id, track.title, artist, "skipped_upload"))
            continue

        _upload_track(track, artist, album, ctx, report)

    if owns_history:
        history.close()
    return report


def _select_tracks(history: HistoryDB, model: str, skip_upload: bool) -> list[DownloadRecord]:
    """Tracks that still need work: not yet separated, or separated but not
    uploaded (unless uploads are skipped)."""
    tracks: list[DownloadRecord] = []
    seen_ids: set[str] = set()
    for dl in history.get_all_downloads():
        needs_separation = not history.is_separated(dl.video_id, model)
        needs_upload = not skip_upload and not history.is_uploaded(dl.video_id, model)
        if (needs_separation or needs_upload) and dl.video_id not in seen_ids:
            tracks.append(dl)
            seen_ids.add(dl.video_id)
    return tracks


def _separate_track(
    track: DownloadRecord, artist: str, ctx: _RunContext, report: PipelineReport
) -> bool:
    """Run source separation for `track` if not already done. Returns True when
    the track is ready for the upload stage, False when it was handled here
    (already-failed QA or an error) and the caller should move on."""
    if ctx.history.is_separated(track.video_id, ctx.model):
        logger.info("Already separated: %s", track.title)
        return True

    logger.info("Separating: %s with %s", track.title, ctx.display_name)
    try:
        audio_path = Path(track.audio_path)
        sep_result = ctx.separator.separate(audio_path, ctx.output_dir / ctx.model)
        qa = check_quality(sep_result.instrumental_path)
        ctx.history.record_separation(
            track.video_id, ctx.model, str(sep_result.instrumental_path), qa.passed
        )
        report.separated += 1

        if not qa.passed:
            reasons = "; ".join(qa.reasons)
            logger.warning("QA failed for %s: %s", track.title, reasons)
            report.failed += 1
            report.tracks.append(
                TrackReport(track.video_id, track.title, artist, "qa_failed", reasons)
            )
            return False
    except Exception as e:
        logger.error("Separation failed for %s: %s", track.title, e)
        report.failed += 1
        report.tracks.append(
            TrackReport(track.video_id, track.title, artist, "separation_failed", str(e))
        )
        return False
    return True


def _upload_track(
    track: DownloadRecord,
    artist: str,
    album: str,
    ctx: _RunContext,
    report: PipelineReport,
) -> None:
    """Render the instrumental video for `track` and upload it, then assign it
    to playlists. All outcomes are recorded on `report`."""
    if ctx.history.is_uploaded(track.video_id, ctx.model):
        logger.info("Already uploaded: %s", track.title)
        report.skipped += 1
        report.tracks.append(
            TrackReport(track.video_id, track.title, artist, "already_uploaded")
        )
        return

    sep_record = ctx.history.get_separation_record(track.video_id, ctx.model)
    if sep_record is None or not sep_record.quality_passed:
        report.skipped += 1
        return
    instrumental_path = Path(sep_record.instrumental_path)

    thumbnail = get_thumbnail_for_track(
        track.video_id, Path(track.thumbnail_path), ctx.tmp_dir
    )
    if not thumbnail or not thumbnail.exists():
        logger.warning("No thumbnail for %s, skipping", track.title)
        report.failed += 1
        report.tracks.append(
            TrackReport(track.video_id, track.title, artist, "no_thumbnail")
        )
        return

    video_path = ctx.output_dir / ctx.model / f"{track.video_id}_instrumental.mp4"
    try:
        render_video(thumbnail, instrumental_path, video_path)
    except Exception as e:
        logger.error("Video render failed for %s: %s", track.title, e)
        report.failed += 1
        report.tracks.append(
            TrackReport(track.video_id, track.title, artist, "render_failed", str(e))
        )
        return

    title = render_video_title(
        ctx.label_config.video_title_template,
        primary_artist=track.channel_name or artist,
        raw_title=track.title,
        all_artists=split_artists(artist),
        album_name=album,
        model_name=ctx.display_name,
        label_name=ctx.label_config.label_name,
        aliases=ctx.label_config.artist_aliases,
    )
    description = render_description(
        ctx.label_config.video_description_template,
        artist_name=artist,
        track_title=track.title,
        album_name=album,
        original_url=track.url,
        original_channel_url=track.channel_url,
        model_name=ctx.display_name,
        label_name=ctx.label_config.label_name,
        channel_url=ctx.label_config.channel_url,
        video_title=title,
    )

    try:
        yt_video_id = upload_video(
            ctx.service, video_path, title, description, ctx.privacy,
            max_total_wait_seconds=ctx.upload_max_wait_seconds,
        )
        ctx.history.record_upload(track.video_id, ctx.model, yt_video_id, ctx.privacy)
        report.uploaded += 1

        try:
            assign_to_playlists(
                ctx.service, ctx.history, ctx.label_config, yt_video_id,
                artist, album, track.channel_name or artist,
                privacy=ctx.privacy, track_title=track.title,
            )
        except Exception as e:
            logger.error("Playlist assignment failed for %s: %s", track.title, e)

        report.tracks.append(
            TrackReport(
                track.video_id, track.title, artist, "uploaded",
                rendered_title=title, youtube_upload_id=yt_video_id,
            )
        )
    except Exception as e:
        logger.error("Upload failed for %s: %s", track.title, e)
        report.failed += 1
        report.tracks.append(
            TrackReport(track.video_id, track.title, artist, "upload_failed", str(e))
        )
