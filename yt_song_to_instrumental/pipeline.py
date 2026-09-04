import logging
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from yt_song_to_instrumental.cleanup import cleanup_track_artifacts
from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.constants import (
    MODEL_DISPLAY_NAMES,
    SHORT_DURATION_SECONDS,
)
from yt_song_to_instrumental.downloader import DownloadedTrack, download_source_video, download_track_audio, download_tracks
from yt_song_to_instrumental.history import DownloadRecord, HistoryDB
from yt_song_to_instrumental.metadata import render_description, render_short_title, render_video_title, strip_topic_suffix
from yt_song_to_instrumental.playlists import assign_to_playlists, split_artists
from yt_song_to_instrumental.quality import _get_duration, check_quality
from yt_song_to_instrumental.separator import get_separator
from yt_song_to_instrumental.separator.base import SeparatorBackend
from yt_song_to_instrumental.thumbnail import get_thumbnail_for_track
from yt_song_to_instrumental.uploader import upload_video
from yt_song_to_instrumental.video_detector import detect_if_music_video
from yt_song_to_instrumental.video_finder import find_and_verify_music_video
from yt_song_to_instrumental.video_render import render_short_video, render_video
from yt_song_to_instrumental.trimmer import detect_silence_threshold, trim_audio_file

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
    cleanup_after_upload: bool
    trim_silence: bool
    trim_silence_threshold_db: float
    preserve_original_video_title: bool
    create_album_playlists: bool = True
    video_channel_url: str | None = None
    trim_start_times: dict[str, float] = field(default_factory=dict)
    shorts_only: bool = False


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
    cleanup_after_upload: bool = True,
    trim_silence: bool = False,
    preserve_original_video_title: bool = False,
    is_uploader: bool = False,
    tab: str = "videos",
    shorts_only: bool = False,
    create_album_playlists: bool = True,
    video_channel_url: str | None = None,
    separator: SeparatorBackend | None = None,
    before_track: Callable[[], None] | None = None,
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
        separator=separator or get_separator(model),
        model=model,
        display_name=MODEL_DISPLAY_NAMES.get(model, model),
        privacy=privacy or config.default_privacy,
        tmp_dir=Path(config.tmp_dir),
        output_dir=Path(config.output_dir),
        upload_max_wait_seconds=upload_max_wait_seconds,
        cleanup_after_upload=cleanup_after_upload,
        trim_silence=trim_silence,
        trim_silence_threshold_db=label_config.trim_silence_threshold_db,
        preserve_original_video_title=preserve_original_video_title or is_uploader,
        create_album_playlists=create_album_playlists,
        video_channel_url=video_channel_url,
        shorts_only=shorts_only,
    )

    target_ids: set[str] | None = None
    if _is_single_video_url(url):
        target_ids = _extract_target_video_ids(url)

    if not skip_download:
        logger.info("Downloading tracks from %s", url)
        downloaded = download_tracks(url, history, ctx.tmp_dir, after_date=after_date, tab=tab)
        report.downloaded = len(downloaded)
        logger.info("Downloaded %d new tracks", report.downloaded)
        if target_ids is None and _is_single_video_url(url) and downloaded:
            target_ids = {t.video_id for t in downloaded}

    shorts_enabled = label_config.upload_short or label_config.upload_short_if_music_video
    for track in _select_tracks(
        history, model, skip_upload, target_ids=target_ids, shorts_enabled=shorts_enabled, shorts_only=shorts_only
    ):
        if before_track is not None:
            before_track()
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


def _is_single_video_url(url: str) -> bool:
    """Return True if `url` points to a single video rather than a channel or playlist."""
    url_lower = url.lower()
    return (
        "watch?v=" in url_lower
        or "youtu.be/" in url_lower
        or "/shorts/" in url_lower
        or "/embed/" in url_lower
        or "/v/" in url_lower
    )


def _extract_target_video_ids(url: str) -> set[str] | None:
    """Extract target video ID from a single-video URL if possible."""
    parsed = urllib.parse.urlparse(url)
    if "youtu.be" in parsed.netloc:
        vid = parsed.path.lstrip("/")
        if vid:
            return {vid}
    elif "youtube.com" in parsed.netloc or "music.youtube.com" in parsed.netloc:
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return {qs["v"][0]}
        parts = parsed.path.split("/")
        if len(parts) >= 3 and parts[1] in ("shorts", "embed", "v"):
            return {parts[2]}
    return None


def sort_tracks_newest_first_preserve_albums(
    tracks: list[DownloadRecord],
) -> list[DownloadRecord]:
    """Sort tracks so newest releases/downloads are processed first, while
    preserving the internal tracklist order (1..N) within each album."""
    if not tracks:
        return []

    groups: dict[str, list[DownloadRecord]] = {}
    group_order: list[str] = []

    for t in tracks:
        clean_album = (t.album or "").strip()
        key = (
            f"album:{t.artist.strip().lower()}:{clean_album.lower()}"
            if clean_album
            else f"single:{t.video_id}"
        )
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(t)

    sorted_keys = sorted(
        group_order,
        key=lambda k: max((t.downloaded_at or "") for t in groups[k]),
        reverse=True,
    )

    result: list[DownloadRecord] = []
    for k in sorted_keys:
        result.extend(groups[k])
    return result


def _select_tracks(
    history: HistoryDB,
    model: str,
    skip_upload: bool,
    target_ids: set[str] | list[str] | None = None,
    shorts_enabled: bool = False,
    shorts_only: bool = False,
) -> list[DownloadRecord]:
    """Tracks that still need work: not yet separated, or separated but not
    uploaded (unless uploads are skipped). If target_ids is provided, restricts
    selection to those video IDs.

    Returns tracks ordered newest-first, while preserving 1..N tracklist order
    within each album."""
    tracks: list[DownloadRecord] = []
    seen_ids: set[str] = set()
    target_set = set(target_ids) if target_ids is not None else None
    for dl in history.get_all_downloads():
        if target_set is not None and dl.video_id not in target_set:
            continue
        needs_separation = not history.is_separated(dl.video_id, model)
        needs_upload = not skip_upload and not shorts_only and not history.is_uploaded(dl.video_id, model)
        needs_short = (
            not skip_upload
            and shorts_enabled
            and not history.is_short_uploaded(dl.video_id, model)
            and history.get_short_status(dl.video_id, model) not in ("skipped_not_music_video", "skipped_disabled")
        )
        if (needs_separation or needs_upload or needs_short) and dl.video_id not in seen_ids:
            tracks.append(dl)
            seen_ids.add(dl.video_id)
    return sort_tracks_newest_first_preserve_albums(tracks)


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

        trim_start_t = 0.0
        if ctx.trim_silence:
            logger.info("Checking for silence/vocals-only sections at start/end...")
            start_t, end_t, orig_dur = detect_silence_threshold(
                sep_result.instrumental_path,
                threshold_db=ctx.trim_silence_threshold_db,
            )
            if start_t > 0.0 or end_t < orig_dur:
                logger.info(
                    "Trimming silence from instrumental: start=%.2fs, end=%.2fs (original duration: %.2fs)",
                    start_t,
                    end_t,
                    orig_dur,
                )
                trimmed_path = sep_result.instrumental_path.parent / "no_vocals_trimmed.wav"
                trim_audio_file(sep_result.instrumental_path, trimmed_path, start_t, end_t)

                # Replace the original instrumental file with the trimmed one
                sep_result.instrumental_path.unlink()
                trimmed_path.rename(sep_result.instrumental_path)

                # Update the duration in sep_result
                sep_result.duration_seconds = end_t - start_t
                ctx.trim_start_times[track.video_id] = start_t
                trim_start_t = start_t

                # Also trim vocals if they exist to keep stems aligned
                if sep_result.vocals_path and sep_result.vocals_path.exists():
                    trimmed_vocals = sep_result.vocals_path.parent / "vocals_trimmed.wav"
                    try:
                        trim_audio_file(sep_result.vocals_path, trimmed_vocals, start_t, end_t)
                        sep_result.vocals_path.unlink()
                        trimmed_vocals.rename(sep_result.vocals_path)
                    except Exception as ve:
                        logger.warning("Failed to trim vocals track: %s", ve)

        qa = check_quality(sep_result.instrumental_path)
        ctx.history.record_separation(
            track.video_id, ctx.model, str(sep_result.instrumental_path), qa.passed, trim_start_seconds=trim_start_t
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


def _upload_short_track(
    track: DownloadRecord,
    artist: str,
    album: str,
    long_form_yt_id: str,
    start_time: float,
    ctx: _RunContext,
    report: PipelineReport,
) -> None:
    if not ctx.label_config.upload_short and not ctx.label_config.upload_short_if_music_video:
        return

    if ctx.history.is_short_uploaded(track.video_id, ctx.model):
        logger.info("Short already uploaded for: %s", track.title)
        return

    sep_record = ctx.history.get_separation_record(track.video_id, ctx.model)
    if sep_record is not None and not sep_record.quality_passed:
        return

    instrumental_path = (
        Path(sep_record.instrumental_path)
        if sep_record
        else ctx.output_dir / ctx.model / ctx.model / track.video_id / "no_vocals.wav"
    )

    if not instrumental_path.exists():
        logger.info("Instrumental track not found on disk for Short: %s. Re-generating instrumental...", track.title)
        audio_path = Path(track.audio_path)
        if not audio_path.exists():
            downloaded_audio = download_track_audio(track.video_id, ctx.tmp_dir)
            if not downloaded_audio or not downloaded_audio.exists():
                logger.warning("Could not download audio to re-generate instrumental for Short: %s", track.title)
                return
            audio_path = downloaded_audio

        try:
            sep_result = ctx.separator.separate(audio_path, ctx.output_dir / ctx.model)
            instrumental_path = sep_result.instrumental_path

            trim_start_t = 0.0
            if ctx.trim_silence:
                start_t, end_t, orig_dur = detect_silence_threshold(
                    instrumental_path, threshold_db=ctx.trim_silence_threshold_db
                )
                if start_t > 0.0 or end_t < orig_dur:
                    trimmed_path = instrumental_path.parent / "no_vocals_trimmed.wav"
                    trim_audio_file(instrumental_path, trimmed_path, start_t, end_t)
                    instrumental_path.unlink()
                    trimmed_path.rename(instrumental_path)
                    trim_start_t = start_t
                    start_time = start_t

            qa = check_quality(instrumental_path)
            ctx.history.record_separation(
                track.video_id, ctx.model, str(instrumental_path), qa.passed, trim_start_seconds=trim_start_t
            )
            if not qa.passed:
                return
            sep_record = ctx.history.get_separation_record(track.video_id, ctx.model)
        except Exception as e:
            logger.error("Failed to re-generate instrumental for Short (%s): %s", track.title, e)
            return

    logger.info("Processing YouTube Short for: %s", track.title)
    source_video = download_source_video(track.video_id, ctx.tmp_dir)
    if not source_video or not source_video.exists():
        logger.warning("Source video could not be downloaded for Short: %s", track.title)
        ctx.history.record_short_status(track.video_id, ctx.model, "source_video_download_failed")
        return

    if start_time == 0.0:
        if sep_record and sep_record.trim_start_seconds > 0.0:
            start_time = sep_record.trim_start_seconds
        elif track.video_id in ctx.trim_start_times:
            start_time = ctx.trim_start_times[track.video_id]

    is_music_vid = None
    if ctx.label_config.upload_short_if_music_video:
        is_music_vid, motion_diff = detect_if_music_video(
            source_video, start_time=start_time, duration=SHORT_DURATION_SECONDS, video_title=track.title
        )
        if not is_music_vid:
            logger.info(
                "Track %s source video detected as static / non-music-video (diff=%.2f); searching YouTube for official music video...",
                track.title,
                motion_diff,
            )
            track_dur = None
            if instrumental_path and instrumental_path.exists():
                try:
                    track_dur = _get_duration(instrumental_path)
                except Exception:
                    track_dur = None
            alt_video, alt_motion = find_and_verify_music_video(
                artist=artist,
                track_title=track.title,
                tmp_dir=ctx.tmp_dir,
                expected_duration=track_dur,
                start_time=start_time,
                video_channel_url=ctx.video_channel_url,
            )
            if alt_video:
                source_video = alt_video
                is_music_vid = True
            else:
                logger.info(
                    "Track %s has no verified music video on YouTube; skipping Short",
                    track.title,
                )
                ctx.history.record_short_status(
                    track.video_id, ctx.model, "skipped_not_music_video", is_music_video=False
                )
                return
        else:
            logger.info("Track %s detected as music video (diff=%.2f)", track.title, motion_diff)

    short_video_path = ctx.output_dir / ctx.model / f"{track.video_id}_short.mp4"
    try:
        render_short_video(
            source_video,
            instrumental_path,
            short_video_path,
            start_time=start_time,
            duration=SHORT_DURATION_SECONDS,
        )
    except Exception as e:
        logger.error("Short video render failed for %s: %s", track.title, e)
        ctx.history.record_short_status(
            track.video_id, ctx.model, "render_failed", is_music_video=is_music_vid
        )
        return

    primary_artist = ctx.label_config.artist_aliases.resolve(
        strip_topic_suffix(track.channel_name or artist)
    )
    full_title = render_video_title(
        ctx.label_config.video_title_template,
        primary_artist=primary_artist,
        raw_title=track.title,
        all_artists=[strip_topic_suffix(a) for a in split_artists(artist)],
        album_name=album,
        model_name=ctx.display_name,
        label_name=ctx.label_config.label_name,
        aliases=ctx.label_config.artist_aliases,
        preserve_original_video_title=ctx.preserve_original_video_title,
    )
    short_title = render_short_title(full_title)

    full_video_url = (
        f"https://www.youtube.com/watch?v={long_form_yt_id}"
        if long_form_yt_id
        else track.url
    )
    short_desc = render_description(
        ctx.label_config.short_description_template,
        artist_name=artist,
        track_title=track.title,
        album_name=album,
        original_url=track.url,
        original_channel_url=track.channel_url,
        model_name=ctx.display_name,
        label_name=ctx.label_config.label_name,
        channel_url=ctx.label_config.channel_url,
        video_title=short_title,
        full_video_url=full_video_url,
    )

    try:
        short_yt_id = upload_video(
            ctx.service,
            short_video_path,
            short_title,
            short_desc,
            ctx.privacy,
            max_total_wait_seconds=ctx.upload_max_wait_seconds,
        )
        ctx.history.record_short_upload(
            track.video_id,
            ctx.model,
            short_yt_id,
            is_music_video=is_music_vid,
            status="uploaded",
        )
        logger.info("Successfully uploaded Short for %s (id: %s)", track.title, short_yt_id)
    except Exception as e:
        logger.error("Short upload failed for %s: %s", track.title, e)
        ctx.history.record_short_status(
            track.video_id, ctx.model, "upload_failed", is_music_video=is_music_vid
        )


def _upload_track(
    track: DownloadRecord,
    artist: str,
    album: str,
    ctx: _RunContext,
    report: PipelineReport,
) -> None:
    """Render the instrumental video for `track` and upload it, then assign it
    to playlists. All outcomes are recorded on `report`."""
    if ctx.shorts_only:
        sep_record = ctx.history.get_separation_record(track.video_id, ctx.model)
        if sep_record is None or not sep_record.quality_passed:
            report.skipped += 1
            return
        upload_rec = ctx.history.get_upload_record(track.video_id, ctx.model)
        long_form_yt_id = upload_rec.youtube_upload_id if upload_rec else ""
        if ctx.label_config.upload_short or ctx.label_config.upload_short_if_music_video:
            if not ctx.history.is_short_uploaded(track.video_id, ctx.model) and ctx.history.get_short_status(track.video_id, ctx.model) not in ("skipped_not_music_video", "skipped_disabled"):
                start_time = 0.0
                if sep_record and sep_record.trim_start_seconds > 0.0:
                    start_time = sep_record.trim_start_seconds
                elif track.video_id in ctx.trim_start_times:
                    start_time = ctx.trim_start_times[track.video_id]
                _upload_short_track(track, artist, album, long_form_yt_id, start_time, ctx, report)

        if ctx.cleanup_after_upload:
            try:
                cleanup_track_artifacts(
                    track.video_id, ctx.model, ctx.tmp_dir, ctx.output_dir,
                )
            except Exception as e:
                logger.warning("Cleanup failed for %s: %s", track.title, e)
        report.tracks.append(
            TrackReport(track.video_id, track.title, artist, "short_processed")
        )
        return

    if ctx.history.is_uploaded(track.video_id, ctx.model):
        upload_rec = ctx.history.get_upload_record(track.video_id, ctx.model)
        long_form_yt_id = upload_rec.youtube_upload_id if upload_rec else ""
        if ctx.label_config.upload_short or ctx.label_config.upload_short_if_music_video:
            if not ctx.history.is_short_uploaded(track.video_id, ctx.model) and ctx.history.get_short_status(track.video_id, ctx.model) not in ("skipped_not_music_video", "skipped_disabled"):
                start_time = 0.0
                sep_record = ctx.history.get_separation_record(track.video_id, ctx.model)
                if sep_record and sep_record.trim_start_seconds > 0.0:
                    start_time = sep_record.trim_start_seconds
                elif track.video_id in ctx.trim_start_times:
                    start_time = ctx.trim_start_times[track.video_id]
                _upload_short_track(track, artist, album, long_form_yt_id, start_time, ctx, report)

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

    primary_artist = ctx.label_config.artist_aliases.resolve(
        strip_topic_suffix(track.channel_name or artist)
    )
    title = render_video_title(
        ctx.label_config.video_title_template,
        primary_artist=primary_artist,
        raw_title=track.title,
        all_artists=[strip_topic_suffix(a) for a in split_artists(artist)],
        album_name=album,
        model_name=ctx.display_name,
        label_name=ctx.label_config.label_name,
        aliases=ctx.label_config.artist_aliases,
        preserve_original_video_title=ctx.preserve_original_video_title,
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
                strip_topic_suffix(artist), album, primary_artist,
                privacy=ctx.privacy, track_title=track.title,
                create_album_playlists=ctx.create_album_playlists,
            )

        except Exception as e:
            logger.error("Playlist assignment failed for %s: %s", track.title, e)

        # Upload Short if configured
        if ctx.label_config.upload_short or ctx.label_config.upload_short_if_music_video:
            start_time = 0.0
            if sep_record and sep_record.trim_start_seconds > 0.0:
                start_time = sep_record.trim_start_seconds
            elif track.video_id in ctx.trim_start_times:
                start_time = ctx.trim_start_times[track.video_id]
            _upload_short_track(track, artist, album, yt_video_id, start_time, ctx, report)

        if ctx.cleanup_after_upload:
            try:
                cleanup_track_artifacts(
                    track.video_id, ctx.model, ctx.tmp_dir, ctx.output_dir,
                )
            except Exception as e:
                # Cleanup failure must never demote a successful upload.
                logger.warning("Cleanup failed for %s: %s", track.title, e)

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
