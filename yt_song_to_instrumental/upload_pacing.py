"""Space uploads using durable history, including after a worker restart."""

import logging
import time
from datetime import datetime, timezone

from yt_song_to_instrumental.constants import (
    DEFAULT_UPLOAD_INTERVAL_SECONDS,
    UPLOAD_PACING_WAIT_LOG,
)
from yt_song_to_instrumental.history import HistoryDB

logger = logging.getLogger(__name__)


def wait_for_upload_slot(history: HistoryDB, interval_seconds: float) -> None:
    """Wait before an upload without reserving slots or changing stage records.

    The normal single worker records successful uploads immediately afterward.
    A stopped wait leaves unfinished work retryable and consumes no slot.
    """
    if interval_seconds <= DEFAULT_UPLOAD_INTERVAL_SECONDS:
        return
    while True:
        last_upload = history.latest_upload_time()
        if last_upload is None:
            return
        elapsed = (datetime.now(timezone.utc) - last_upload).total_seconds()
        remaining = interval_seconds - elapsed
        if remaining <= DEFAULT_UPLOAD_INTERVAL_SECONDS:
            return
        logger.info(UPLOAD_PACING_WAIT_LOG, remaining)
        time.sleep(remaining)
