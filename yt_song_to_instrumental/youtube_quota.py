"""Shared, conservative daily YouTube budgets for all managed API callers."""
import fcntl
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.http import HttpRequest

from yt_song_to_instrumental.constants import (
    YOUTUBE_QUOTA_FILENAME, YOUTUBE_QUOTA_TIMEZONE, YOUTUBE_QUOTA_NORMAL,
    YOUTUBE_QUOTA_REPAIR, YOUTUBE_QUOTA_DEDICATED, YOUTUBE_API_READ_COST,
    YOUTUBE_API_WRITE_COST, YOUTUBE_QUOTA_TIMEOUT, YOUTUBE_QUOTA_ERROR,
)

_lane = ContextVar("youtube_quota_lane", default="normal")


class QuotaReserved(RuntimeError):
    """The caller's budget is spent; leave other callers' reservations intact."""


class QuotaLedger:
    def __init__(self, path: Path, now=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._mutex = threading.RLock()
        self._depth = 0
        self._file = None
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS quota_usage (
                    day TEXT, bucket TEXT, lane TEXT, units INTEGER NOT NULL,
                    PRIMARY KEY(day, bucket, lane));
                CREATE TABLE IF NOT EXISTS repair_retry (day TEXT PRIMARY KEY, not_before REAL);
                CREATE TABLE IF NOT EXISTS repair_runs (
                    day TEXT PRIMARY KEY, status TEXT NOT NULL, moves INTEGER NOT NULL,
                    remaining INTEGER, unknown INTEGER, checked INTEGER);
                CREATE TABLE IF NOT EXISTS repair_events (
                    id INTEGER PRIMARY KEY, day TEXT, playlist_id TEXT,
                    item_id TEXT, position INTEGER, state TEXT);
                CREATE TABLE IF NOT EXISTS repair_playlists (
                    playlist_id TEXT PRIMARY KEY, remaining INTEGER NOT NULL, verified_at TEXT);
                CREATE TABLE IF NOT EXISTS repair_anchors (
                    playlist_id TEXT, item_id TEXT, position INTEGER,
                    PRIMARY KEY(playlist_id, item_id));
                CREATE TABLE IF NOT EXISTS repair_metadata (
                    youtube_video_id TEXT PRIMARY KEY, source_video_id TEXT NOT NULL);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=YOUTUBE_QUOTA_TIMEOUT)

    def day(self):
        return self.now().astimezone(ZoneInfo(YOUTUBE_QUOTA_TIMEZONE)).date().isoformat()

    @contextmanager
    def lock(self):
        """Cross-process writer lock; nested requests in a repair batch reuse it."""
        with self._mutex:
            if not self._depth:
                self._file = self.path.with_suffix('.lock').open('a')
                fcntl.flock(self._file, fcntl.LOCK_EX)
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if not self._depth:
                    fcntl.flock(self._file, fcntl.LOCK_UN)
                    self._file.close()

    @contextmanager
    def repair_lane(self):
        token = _lane.set('repair')
        try:
            yield
        finally:
            _lane.reset(token)

    def charge(self, method_id, attempts=1):
        if method_id in ('youtube.videos.insert', 'youtube.search.list'):
            bucket = method_id
            cost = YOUTUBE_API_READ_COST
            limit = YOUTUBE_QUOTA_DEDICATED
        else:
            bucket = 'general'
            cost = YOUTUBE_API_READ_COST if method_id.endswith('.list') else YOUTUBE_API_WRITE_COST
            limit = YOUTUBE_QUOTA_REPAIR if _lane.get() == 'repair' else YOUTUBE_QUOTA_NORMAL
        lane = _lane.get() if bucket == 'general' else 'shared'
        cost *= attempts
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT units FROM quota_usage WHERE day=? AND bucket=? AND lane=?',
                             (self.day(), bucket, lane)).fetchone()
            used = row[0] if row else 0
            if used + cost > limit:
                raise QuotaReserved(YOUTUBE_QUOTA_ERROR)
            db.execute('INSERT OR REPLACE INTO quota_usage VALUES (?, ?, ?, ?)',
                       (self.day(), bucket, lane, used + cost))


def quota_path(token_file):
    return Path(token_file).resolve().parent / 'data' / YOUTUBE_QUOTA_FILENAME


def metered_request_builder(ledger):
    class MeteredRequest(HttpRequest):
        def execute(self, http=None, num_retries=0):
            if self.resumable:
                return super().execute(http=http, num_retries=num_retries)
            with ledger.lock():
                ledger.charge(self.methodId, num_retries + 1)
                return super().execute(http=http, num_retries=num_retries)

        def next_chunk(self, http=None, num_retries=0):
            with ledger.lock():
                if self.resumable_uri is None:
                    ledger.charge(self.methodId, num_retries + 1)
                return super().next_chunk(http=http, num_retries=num_retries)
    return MeteredRequest
