import logging
import re
from pathlib import Path

from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.constants import (
    PRIORITY_ERROR_NO_TRACK,
    PRIORITY_ERROR_REPORT_PREFIX,
    PRIORITY_SUCCESS_TRACK_STATUSES,
    YOUTUBE_CANONICAL_VIDEO_URL,
    YOUTUBE_VIDEO_ID_PATTERN,
)
from yt_song_to_instrumental.history import HistoryDB, PriorityRequest
from yt_song_to_instrumental.pipeline import (
    PipelineReport,
    _extract_target_video_ids,
    _is_single_video_url,
    process_url,
)
from yt_song_to_instrumental.separator.base import SeparatorBackend

logger = logging.getLogger(__name__)


def enqueue_priority_request(
    url: str,
    db_path: str | Path | None = None,
) -> PriorityRequest:
    """Put one YouTube video at the front of the instrumental request queue."""
    normalized_url = _normalize_video_url(url)
    history = HistoryDB(db_path)
    try:
        return history.enqueue_priority_request(normalized_url)
    finally:
        history.close()


def process_priority_requests(
    *,
    config: AppConfig,
    label_config: LabelConfig,
    service,
    history: HistoryDB,
    separator: SeparatorBackend,
    model_name: str,
    privacy: str | None,
    upload_max_wait_seconds: float | None,
    cleanup_after_upload: bool,
    trim_silence: bool,
) -> list[tuple[PriorityRequest, PipelineReport]]:
    """Drain priority requests newest-first through the normal pipeline."""
    results: list[tuple[PriorityRequest, PipelineReport]] = []

    while request := history.claim_next_priority_request():
        logger.info("Processing priority request #%d: %s", request.id, request.url)
        try:
            report = process_url(
                url=request.url,
                config=config,
                label_config=label_config,
                service=service,
                model_name=model_name,
                privacy=privacy,
                history=history,
                separator=separator,
                upload_max_wait_seconds=upload_max_wait_seconds,
                cleanup_after_upload=cleanup_after_upload,
                trim_silence=trim_silence,
            )
        except Exception as exc:
            history.fail_priority_request(request.id, str(exc))
            logger.exception("Priority request #%d failed", request.id)
            continue

        results.append((request, report))
        successful = any(
            track.status in PRIORITY_SUCCESS_TRACK_STATUSES
            for track in report.tracks
        )
        if report.failed == 0 and successful:
            history.complete_priority_request(request.id)
            logger.info("Priority request #%d completed", request.id)
            continue

        reason = _report_failure_reason(report)
        history.fail_priority_request(request.id, reason)
        logger.error("Priority request #%d failed: %s", request.id, reason)

    return results


def _normalize_video_url(url: str) -> str:
    candidate = url.strip()
    if not _is_single_video_url(candidate):
        raise ValueError("priority requests require a single YouTube video URL")

    video_ids = _extract_target_video_ids(candidate)
    if video_ids is None or len(video_ids) != 1:
        raise ValueError("could not extract a YouTube video ID from the priority request")

    video_id = next(iter(video_ids))
    if re.fullmatch(YOUTUBE_VIDEO_ID_PATTERN, video_id) is None:
        raise ValueError("priority request contains an invalid YouTube video ID")
    return YOUTUBE_CANONICAL_VIDEO_URL.format(video_id=video_id)


def _report_failure_reason(report: PipelineReport) -> str:
    if not report.tracks:
        return PRIORITY_ERROR_NO_TRACK
    statuses = ", ".join(track.status for track in report.tracks)
    return f"{PRIORITY_ERROR_REPORT_PREFIX}{statuses}"
