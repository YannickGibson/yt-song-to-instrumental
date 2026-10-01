"""Space uploads using durable history, including after a worker restart."""

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from statistics import NormalDist

from yt_song_to_instrumental.constants import (
    DEFAULT_UPLOAD_INTERVAL_SECONDS,
    SOURCE_DATE_FORMAT,
    SOURCE_SCAN_POLL_SECONDS,
    DEFAULT_UPLOAD_INTERVAL_JITTER_SECONDS,
    UPLOAD_INTERVAL_JITTER_SIGMA_BOUND,
    UPLOAD_INTERVAL_JITTER_ROUND_DIGITS,
    UPLOAD_PACING_WAIT_LOG,
)
from yt_song_to_instrumental.history import HistoryDB

logger = logging.getLogger(__name__)


class UploadDeferred(Exception):
    """Fresh source discovery or a priority request changed the next candidate."""


def is_recent_release(release_date: str, window_days: int) -> bool:
    if not release_date or window_days <= DEFAULT_UPLOAD_INTERVAL_SECONDS:
        return False
    try:
        released = datetime.strptime(release_date, SOURCE_DATE_FORMAT).date()
    except (ValueError, TypeError):
        return False
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=window_days) <= released <= today


def _target_interval_seconds(last_upload: datetime, interval_seconds: float, jitter_seconds: float) -> float:
    """Choose a bounded Gaussian gap, fixed by the durable upload timestamp."""
    if jitter_seconds <= DEFAULT_UPLOAD_INTERVAL_JITTER_SECONDS:
        return interval_seconds
    distribution = NormalDist(
        DEFAULT_UPLOAD_INTERVAL_JITTER_SECONDS,
        jitter_seconds / UPLOAD_INTERVAL_JITTER_SIGMA_BOUND,
    )
    lower = distribution.cdf(-jitter_seconds)
    upper = distribution.cdf(jitter_seconds)
    quantile = lower + random.Random(last_upload.isoformat()).random() * (upper - lower)
    return round(interval_seconds + distribution.inv_cdf(quantile), UPLOAD_INTERVAL_JITTER_ROUND_DIGITS)


def wait_for_upload_slot(
    history: HistoryDB,
    interval_seconds: float,
    jitter_seconds: float = DEFAULT_UPLOAD_INTERVAL_JITTER_SECONDS,
    *, check: Callable[[], None] | None = None,
) -> None:
    """Wait before an upload without reserving slots or changing stage records.

    The normal single worker records successful uploads immediately afterward.
    A stopped wait leaves unfinished work retryable and consumes no slot.
    """
    if interval_seconds <= DEFAULT_UPLOAD_INTERVAL_SECONDS:
        if check is not None:
            check()
        return
    while True:
        if check is not None:
            check()
        last_upload = history.latest_upload_time()
        if last_upload is None:
            return
        elapsed = (datetime.now(timezone.utc) - last_upload).total_seconds()
        remaining = _target_interval_seconds(last_upload, interval_seconds, jitter_seconds) - elapsed
        if remaining <= DEFAULT_UPLOAD_INTERVAL_SECONDS:
            return
        logger.info(UPLOAD_PACING_WAIT_LOG, remaining)
        time.sleep(min(remaining, SOURCE_SCAN_POLL_SECONDS) if check is not None else remaining)
