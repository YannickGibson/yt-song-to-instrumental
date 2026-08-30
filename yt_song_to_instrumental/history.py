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
    trim_start_seconds: float = 0.0


@dataclass
class UploadRecord:
    id: int
    video_id: str
    model: str
    youtube_upload_id: str
    uploaded_at: str
    privacy: str
    youtube_short_upload_id: str = ""
    short_uploaded_at: str = ""
    short_status: str = ""
    is_music_video: int | None = None


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
    trim_start_seconds REAL NOT NULL DEFAULT 0.0,
    UNIQUE(video_id, model)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    model TEXT NOT NULL,
    youtube_upload_id TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    privacy TEXT NOT NULL,
    youtube_short_upload_id TEXT NOT NULL DEFAULT '',
    short_uploaded_at TEXT NOT NULL DEFAULT '',
    short_status TEXT NOT NULL DEFAULT '',
    is_music_video INTEGER,
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
        self._migrate()

    def _migrate(self):
        try:
            existing_sep_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(separations)").fetchall()}
            if "trim_start_seconds" not in existing_sep_cols:
                self._conn.execute("ALTER TABLE separations ADD COLUMN trim_start_seconds REAL NOT NULL DEFAULT 0.0")

            existing_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(uploads)").fetchall()}
            new_cols = {
                "youtube_short_upload_id": "TEXT NOT NULL DEFAULT ''",
                "short_uploaded_at": "TEXT NOT NULL DEFAULT ''",
                "short_status": "TEXT NOT NULL DEFAULT ''",
                "is_music_video": "INTEGER",
            }
            for col_name, col_type in new_cols.items():
                if col_name not in existing_cols:
                    self._conn.execute(f"ALTER TABLE uploads ADD COLUMN {col_name} {col_type}")
            self._conn.commit()
        except Exception:
            pass

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
        trim_start_seconds: float = 0.0,
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO separations
            (video_id, model, instrumental_path, separated_at, quality_passed, trim_start_seconds)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (video_id, model, instrumental_path, self._now(), int(quality_passed), float(trim_start_seconds)),
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
            "SELECT youtube_upload_id FROM uploads WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        if row is None:
            return False
        return bool(row["youtube_upload_id"])

    def record_upload(
        self,
        video_id: str,
        model: str,
        youtube_upload_id: str,
        privacy: str,
    ) -> None:
        self._conn.execute(
            """INSERT INTO uploads
            (video_id, model, youtube_upload_id, uploaded_at, privacy)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id, model) DO UPDATE SET
                youtube_upload_id = excluded.youtube_upload_id,
                uploaded_at = excluded.uploaded_at,
                privacy = excluded.privacy""",
            (video_id, model, youtube_upload_id, self._now(), privacy),
        )
        self._conn.commit()

    def record_short_upload(
        self,
        video_id: str,
        model: str,
        youtube_short_upload_id: str,
        is_music_video: bool | None = None,
        status: str = "uploaded",
    ) -> None:
        mv_val = int(is_music_video) if is_music_video is not None else None
        self._conn.execute(
            """INSERT INTO uploads
            (video_id, model, youtube_upload_id, uploaded_at, privacy,
             youtube_short_upload_id, short_uploaded_at, short_status, is_music_video)
            VALUES (?, ?, '', '', '', ?, ?, ?, ?)
            ON CONFLICT(video_id, model) DO UPDATE SET
                youtube_short_upload_id = excluded.youtube_short_upload_id,
                short_uploaded_at = excluded.short_uploaded_at,
                short_status = excluded.short_status,
                is_music_video = COALESCE(excluded.is_music_video, uploads.is_music_video)""",
            (video_id, model, youtube_short_upload_id, self._now(), status, mv_val),
        )
        self._conn.commit()

    def record_short_status(
        self,
        video_id: str,
        model: str,
        status: str,
        is_music_video: bool | None = None,
    ) -> None:
        mv_val = int(is_music_video) if is_music_video is not None else None
        self._conn.execute(
            """INSERT INTO uploads
            (video_id, model, youtube_upload_id, uploaded_at, privacy,
             short_status, is_music_video)
            VALUES (?, ?, '', '', '', ?, ?)
            ON CONFLICT(video_id, model) DO UPDATE SET
                short_status = excluded.short_status,
                is_music_video = COALESCE(excluded.is_music_video, uploads.is_music_video)""",
            (video_id, model, status, mv_val),
        )
        self._conn.commit()

    def is_short_uploaded(self, video_id: str, model: str) -> bool:
        row = self._conn.execute(
            "SELECT youtube_short_upload_id, short_status FROM uploads WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        if row is None:
            return False
        return bool(row["youtube_short_upload_id"]) or (row["short_status"] == "uploaded")

    def get_upload_record(self, video_id: str, model: str) -> UploadRecord | None:
        row = self._conn.execute(
            "SELECT * FROM uploads WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        if row is None:
            return None
        return UploadRecord(**dict(row))

    def get_short_status(self, video_id: str, model: str) -> str | None:
        row = self._conn.execute(
            "SELECT short_status FROM uploads WHERE video_id = ? AND model = ?",
            (video_id, model),
        ).fetchone()
        if row is None:
            return None
        return row["short_status"] or None

    def get_all_uploads(self) -> list[UploadRecord]:
        rows = self._conn.execute("SELECT * FROM uploads ORDER BY uploaded_at").fetchall()
        return [UploadRecord(**dict(r)) for r in rows]

    def get_pending_upload(self, model: str) -> list[SeparationRecord]:
        rows = self._conn.execute(
            """SELECT s.* FROM separations s
            LEFT JOIN uploads u ON s.video_id = u.video_id AND s.model = u.model
            WHERE (u.id IS NULL OR u.youtube_upload_id = '') AND s.model = ? AND s.quality_passed = 1
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
