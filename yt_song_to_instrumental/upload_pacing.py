"""Space uploads using durable history, including after a worker restart."""

import logging
import random
import time
from datetime import datetime, timezone
from statistics import NormalDist

from yt_song_to_instrumental.constants import (
    DEFAULT_UPLOAD_INTERVAL_SECONDS,
    DEFAULT_UPLOAD_INTERVAL_JITTER_SECONDS,
    UPLOAD_INTERVAL_JITTER_SIGMA_BOUND,
    UPLOAD_INTERVAL_JITTER_ROUND_DIGITS,
    UPLOAD_PACING_WAIT_LOG,
)
from yt_song_to_instrumental.history import HistoryDB

logger = logging.getLogger(__name__)


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
) -> None:
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
        remaining = _target_interval_seconds(last_upload, interval_seconds, jitter_seconds) - elapsed
        if remaining <= DEFAULT_UPLOAD_INTERVAL_SECONDS:
            return
        logger.info(UPLOAD_PACING_WAIT_LOG, remaining)
        time.sleep(remaining)
