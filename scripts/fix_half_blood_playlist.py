import logging
import sqlite3
import yt_dlp

from yt_song_to_instrumental.config import YouTubeConfig, load_label_config
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.uploader import authenticate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PLAYLIST_ID = "PLURM8BoYIj48"
HALF_BLOOD_RELEASE_PLAYLIST = "https://www.youtube.com/playlist?list=OLAK5uy_kgFp7Ksnky9RyaCRpMDm1kucbjQ9agQHY"


def main():
    yt_cfg = YouTubeConfig()
    service = authenticate(yt_cfg.client_secrets_file, yt_cfg.token_file)

    # 1. Clear existing items from playlist PLURM8BoYIj48
    logger.info("Clearing existing items from playlist %s...", PLAYLIST_ID)
    res = service.playlistItems().list(playlistId=PLAYLIST_ID, part="snippet", maxResults=50).execute()
    items = res.get("items", [])
    for item in items:
        item_id = item["id"]
        title = item["snippet"]["title"]
        logger.info("Deleting item %s ('%s')...", item_id, title)
        try:
            service.playlistItems().delete(id=item_id).execute()
        except Exception as e:
            logger.warning("Failed to delete item %s: %s", item_id, e)

    # 2. Get official track list and order for Half Blood
    logger.info("Extracting official track sequence for Half Blood album...")
    ydl = yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True})
    pl_info = ydl.extract_info(HALF_BLOOD_RELEASE_PLAYLIST, download=False)
    official_tracks = pl_info.get("entries", [])

    # Build title matching map from history.db uploads
    history = HistoryDB()
    query = """
    SELECT d.video_id, d.title, u.youtube_upload_id
    FROM downloads d
    JOIN uploads u ON d.video_id = u.video_id
    WHERE d.artist LIKE '%slayr%' OR d.channel_name LIKE '%slayr%' OR d.channel_url LIKE '%UCivyc3VgQwCqqlr6SlnKQSw%'
    """
    rows = history._conn.execute(query).fetchall()
    history.close()

    # Map raw title / clean title to youtube_upload_id
    title_to_upload_id: dict[str, str] = {}
    for r in rows:
        t_clean = r["title"].replace("slayr - ", "").strip().lower()
        title_to_upload_id[t_clean] = r["youtube_upload_id"]

    logger.info("Re-building playlist %s with all 11 tracks in exact sequence...", PLAYLIST_ID)
    for idx, tr in enumerate(official_tracks, start=1):
        tr_title = tr.get("title", "").strip()
        tr_clean = tr_title.replace("slayr - ", "").strip().lower()
        # Find matching upload ID
        matched_upload_id = None
        for key, upload_id in title_to_upload_id.items():
            if key in tr_clean or tr_clean in key:
                matched_upload_id = upload_id
                break

        if matched_upload_id:
            logger.info("Adding Track %2d/%d: '%s' (Upload ID: %s) to playlist %s...", idx, len(official_tracks), tr_title, matched_upload_id, PLAYLIST_ID)
            body = {
                "snippet": {
                    "playlistId": PLAYLIST_ID,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": matched_upload_id,
                    },
                },
            }
            service.playlistItems().insert(part="snippet", body=body).execute()
        else:
            logger.warning("Could not find upload for Track %2d: '%s'", idx, tr_title)

    logger.info("Playlist %s rebuild complete!", PLAYLIST_ID)


if __name__ == "__main__":
    main()
