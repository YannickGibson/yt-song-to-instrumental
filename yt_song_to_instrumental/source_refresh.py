"""Refresh every configured artist before upload admission in the single worker."""
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import time

from yt_song_to_instrumental import constants as C
from yt_song_to_instrumental.config import Source
from yt_song_to_instrumental.downloader import download_tracks, enumerate_videos
from yt_song_to_instrumental.pipeline import _select_tracks
from yt_song_to_instrumental.upload_pacing import UploadDeferred, is_recent_release

logger = logging.getLogger(__name__)


class SourceCoordinator:
    def __init__(self, sources, history, tmp_dir, model, label_config, shorts_only=False):
        self.sources = sources
        self.history = history
        self.tmp_dir = Path(tmp_dir)
        self.model = model
        self.label_config = label_config
        self.shorts_only = shorts_only
        self.attempted = set()
        self.retry_after = {}
        self.failed_sources = set()

    def refresh(self):
        logger.info(C.SOURCE_SCAN_START_LOG, len(self.sources))
        downloaded = C.SOURCE_EMPTY_COUNT
        failed = set()
        # Only read-only enumeration runs concurrently. Downloads, SQLite,
        # separation and upload remain in the one managed worker thread.
        with ThreadPoolExecutor(max_workers=C.SOURCE_SCAN_WORKERS) as pool:
            scans = [(source, pool.submit(enumerate_videos, source.url,
                      after_date=source.after_date, tab=source.tab, strict=True))
                     for source in self.sources]
            for source, future in scans:
                try:
                    entries = future.result()
                    downloaded += len(download_tracks(source.url, self.history, self.tmp_dir,
                                      after_date=source.after_date, tab=source.tab, entries=entries))
                    for entry in entries:
                        video_id = entry.get(C.SOURCE_ENTRY_ID)
                        track = self.history.get_download(video_id) if video_id else None
                        if track is not None and (source.after_date is None or not track.release_date
                                                  or track.release_date >= source.after_date):
                            self.history.record_source_membership(video_id, source.url, source.tab)
                except Exception as error:
                    failed.add(source)
                    logger.warning(C.SOURCE_SCAN_FAILED_LOG, source.url, error)
        self.failed_sources = failed
        logger.info(C.SOURCE_SCAN_COMPLETE_LOG, len(self.sources), downloaded, len(failed))

    def source_for(self, track):
        memberships = self.history.source_memberships(track.video_id)
        return next((source for source in self.sources if (source.url, source.tab) in memberships),
                    Source(url=track.url, after_date=None))

    def candidates(self, current=None):
        for video_id, deadline in tuple(self.retry_after.items()):
            if time.monotonic() >= deadline:
                self.attempted.discard(video_id)
                del self.retry_after[video_id]
        tracks = _select_tracks(
            self.history, self.model, False,
            shorts_enabled=self.label_config.upload_short or self.label_config.upload_short_if_music_video,
            shorts_only=self.shorts_only,
        )
        tracks = [track for track in tracks if track.video_id not in self.attempted or track.video_id == current]
        # Stable partition preserves release/album ordering inside each group.
        return sorted(tracks, key=lambda track: not is_recent_release(
            track.release_date, self.label_config.recent_upload_window_days))

    def record_attempt_result(self, video_id, reports):
        if any(report.status in C.RETRYABLE_PIPELINE_FAILURE_STATUSES for report in reports):
            self.retry_after[video_id] = time.monotonic() + C.SOURCE_RETRY_SECONDS

    def before_upload(self, track, priority_request=False):
        self.refresh()
        if priority_request:
            return
        if self.history.has_pending_priority_requests():
            raise UploadDeferred()
        candidates = self.candidates(current=track.video_id)
        if candidates and candidates[C.SOURCE_FIRST_INDEX].video_id != track.video_id:
            raise UploadDeferred()
