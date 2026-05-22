import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from yt_song_to_instrumental.constants import DATA_DIR, DB_FILENAME


@dataclass
class DownloadRecord:
    video_id: str
    url: str
    title: str
    artist: str
    album: str
    channel_name: str
    channel_url: str
    downloaded_at: str
    audio_path: str
    thumbnail_path: str


@dataclass
class SeparationRecord:
    id: int
    video_id: str
    model: str
    instrumental_path: str
    separated_at: str
    quality_passed: bool


@dataclass
class UploadRecord:
    id: int
    video_id: str
    model: str
    youtube_upload_id: str
    uploaded_at: str
    privacy: str


@dataclass
class PlaylistRecord:
    id: int
    playlist_type: str
    artist: str
    album: str | None
    youtube_playlist_id: str
    created_at: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    video_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    channel_name TEXT NOT NULL DEFAULT '',
    channel_url TEXT NOT NULL DEFAULT '',
    downloaded_at TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    thumbnail_path TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS separations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    model TEXT NOT NULL,
    instrumental_path TEXT NOT NULL,
    separated_at TEXT NOT NULL,
    quality_passed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(video_id, model)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    model TEXT NOT NULL,
    youtube_upload_id TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    privacy TEXT NOT NULL,
    UNIQUE(video_id, model)
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_type TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    youtube_playlist_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(playlist_type, artist, album)
);
"""


class HistoryDB:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = DATA_DIR / DB_FILENAME
        self._db_path = Path(db_path)
        if str(self._db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self):
        self._conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # --- Downloads ---

    def is_downloaded(self, video_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM downloads WHERE video_id = ?", (video_id,)
        ).fetchone()
        return row is not None

    def record_download(
        self,
        video_id: str,
        url: str,
        title: str,
        artist: str,
        album: str,
        channel_name: str,
        channel_url: str,
        audio_path: str,
        thumbnail_path: str,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO downloads
            (video_id, url, title, artist, album, channel_name, channel_url,
             downloaded_at, audio_path, thumbnail_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (video_id, url, title, artist, album, channel_name, channel_url,
             self._now(), audio_path, thumbnail_path),
        )
        self._conn.commit()

    def get_download(self, video_id: str) -> DownloadRecord | None:
        row = self._conn.execute(
            "SELECT * FROM downloads WHERE video_id = ?", (video_id,)
        ).fetchone()
        if row is None:
            return None
        return DownloadRecord(**dict(row))

    def get_all_downloads(self) -> list[DownloadRecord]:
        rows = self._conn.execute("SELECT * FROM downloads ORDER BY downloaded_at").fetchall()
        return [DownloadRecord(**dict(r)) for r in rows]

    # --- Separations ---

    def is_separated(self, video_id: str, model: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM separations WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        return row is not None

    def record_separation(
        self,
        video_id: str,
        model: str,
        instrumental_path: str,
        quality_passed: bool,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO separations
            (video_id, model, instrumental_path, separated_at, quality_passed)
            VALUES (?, ?, ?, ?, ?)""",
            (video_id, model, instrumental_path, self._now(), int(quality_passed)),
        )
        self._conn.commit()

    def get_unprocessed(self, model: str) -> list[DownloadRecord]:
        rows = self._conn.execute(
            """SELECT d.* FROM downloads d
            LEFT JOIN separations s ON d.video_id = s.video_id AND s.model = ?
            WHERE s.id IS NULL
            ORDER BY d.downloaded_at""",
            (model,),
        ).fetchall()
        return [DownloadRecord(**dict(r)) for r in rows]

    def get_separation_record(self, video_id: str, model: str) -> SeparationRecord | None:
        row = self._conn.execute(
            "SELECT * FROM separations WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        if row is None:
            return None
        fields = dict(row)
        fields["quality_passed"] = bool(fields["quality_passed"])
        return SeparationRecord(**fields)

    # --- Uploads ---

    def is_uploaded(self, video_id: str, model: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM uploads WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        return row is not None

    def record_upload(
        self,
        video_id: str,
        model: str,
        youtube_upload_id: str,
        privacy: str,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO uploads
            (video_id, model, youtube_upload_id, uploaded_at, privacy)
            VALUES (?, ?, ?, ?, ?)""",
            (video_id, model, youtube_upload_id, self._now(), privacy),
        )
        self._conn.commit()

    def get_pending_upload(self, model: str) -> list[SeparationRecord]:
        rows = self._conn.execute(
            """SELECT s.* FROM separations s
            LEFT JOIN uploads u ON s.video_id = u.video_id AND s.model = u.model
            WHERE u.id IS NULL AND s.model = ? AND s.quality_passed = 1
            ORDER BY s.separated_at""",
            (model,),
        ).fetchall()
        return [SeparationRecord(**dict(r)) for r in rows]

    # --- Playlists ---

    def get_playlist(self, playlist_type: str, artist: str, album: str | None = None) -> PlaylistRecord | None:
        row = self._conn.execute(
            "SELECT * FROM playlists WHERE playlist_type = ? AND artist = ? AND album IS ?",
            (playlist_type, artist, album),
        ).fetchone()
        if row is None:
            return None
        return PlaylistRecord(**dict(row))

    def record_playlist(
        self,
        playlist_type: str,
        artist: str,
        album: str | None,
        youtube_playlist_id: str,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO playlists
            (playlist_type, artist, album, youtube_playlist_id, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (playlist_type, artist, album, youtube_playlist_id, self._now()),
        )
        self._conn.commit()
