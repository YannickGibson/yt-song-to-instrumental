import logging
import sqlite3
import yt_dlp

from yt_song_to_instrumental.config import YouTubeConfig, load_label_config
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.metadata import strip_topic_suffix
from yt_song_to_instrumental.playlists import assign_to_playlists
from yt_song_to_instrumental.uploader import authenticate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SLAYR_URL = "https://www.youtube.com/channel/UCivyc3VgQwCqqlr6SlnKQSw/releases"


def main():
    label_config = load_label_config()
    yt_cfg = YouTubeConfig()
    service = authenticate(yt_cfg.client_secrets_file, yt_cfg.token_file)

    logger.info("Scanning slayr Releases tab to map video IDs & track order to Album names...")
    ydl = yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True})
    res = ydl.extract_info(SLAYR_URL, download=False)

    video_to_album: dict[str, str] = {}
    video_to_track_order: dict[str, int] = {}
    album_track_counts: dict[str, int] = {}

    for e in (res.get("entries") or []):
        pl_url = e.get("url") or e.get("webpage_url")
        if not pl_url:
            continue
        try:
            pl_info = ydl.extract_info(pl_url, download=False)
            album_name = (pl_info.get("title") or "").strip()
            tracks = pl_info.get("entries") or []
            album_track_counts[album_name] = len(tracks)
            logger.info("Discovered release album: '%s' (%d tracks)", album_name, len(tracks))
            for idx, track in enumerate(tracks, start=1):
                vid = track.get("id")
                if vid and album_name:
                    video_to_album[vid] = album_name
                    video_to_track_order[vid] = idx
        except Exception as ex:
            logger.warning("Failed to extract playlist %s: %s", pl_url, ex)

    history = HistoryDB()

    try:
        # Update downloads table in history.db
        logger.info("Updating album metadata in history.db for slayr downloads...")
        updated_count = 0
        for vid, album in video_to_album.items():
            count = album_track_counts.get(album, 0)
            if count <= 1:
                continue
            row = history._conn.execute("SELECT video_id, album FROM downloads WHERE video_id = ?", (vid,)).fetchone()
            if row:
                history._conn.execute("UPDATE downloads SET album = ? WHERE video_id = ?", (album, vid))
                updated_count += 1
        history._conn.commit()
        logger.info("Updated album metadata for %d slayr tracks in DB.", updated_count)

        # Now find all uploaded slayr tracks and group them by album in EXACT track sequence order
        logger.info("Fetching uploaded slayr tracks...")
        query = """
        SELECT d.video_id, d.title, d.artist, d.album, u.youtube_upload_id, u.privacy
        FROM downloads d
        JOIN uploads u ON d.video_id = u.video_id
        WHERE d.artist LIKE '%slayr%' OR d.channel_name LIKE '%slayr%' OR d.channel_url LIKE '%UCivyc3VgQwCqqlr6SlnKQSw%'
        """
        rows = history._conn.execute(query).fetchall()
        logger.info("Found %d uploaded slayr tracks.", len(rows))

        # Group by album
        albums_to_tracks: dict[str, list] = {}
        for r in rows:
            rec = dict(r)
            vid = rec["video_id"]
            album = rec["album"] or video_to_album.get(vid, "")
            if not album or album_track_counts.get(album, 0) <= 1:
                continue
            track_order = video_to_track_order.get(vid, 999)
            rec["_track_order"] = track_order
            albums_to_tracks.setdefault(album, []).append(rec)

        assigned_count = 0
        # Process each album in exact track sequence order (1..N)
        for album_name, track_records in albums_to_tracks.items():
            # SORT STRICTLY BY ORIGINAL TRACK ORDER
            sorted_tracks = sorted(track_records, key=lambda x: x["_track_order"])
            logger.info("Processing album '%s' (%d uploaded tracks) in strict track sequence...", album_name, len(sorted_tracks))

            for rec in sorted_tracks:
                yt_upload_id = rec["youtube_upload_id"]
                artist = rec["artist"]
                privacy = rec["privacy"] or "public"
                title = rec["title"]
                primary_artist = label_config.artist_aliases.resolve(strip_topic_suffix(artist))

                try:
                    logger.info("Adding Track %d ('%s') to album playlist '%s'...", rec["_track_order"], title, album_name)
                    assign_to_playlists(
                        service=service,
                        history=history,
                        label_config=label_config,
                        video_id=yt_upload_id,
                        artist=strip_topic_suffix(artist),
                        album=album_name,
                        primary_artist=primary_artist,
                        privacy=privacy,
                        track_title=title,
                    )
                    assigned_count += 1
                except Exception as ex:
                    logger.error("Failed to assign video %s to playlist: %s", yt_upload_id, ex)

        logger.info("Completed! Processed %d tracks into album playlists in exact track sequence.", assigned_count)
    finally:
        history.close()


if __name__ == "__main__":
    main()
