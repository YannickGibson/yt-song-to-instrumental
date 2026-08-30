import logging
import sqlite3
import yt_dlp

from yt_song_to_instrumental.config import YouTubeConfig, load_label_config
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.metadata import strip_topic_suffix
from yt_song_to_instrumental.playlists import get_or_create_album_playlist
from yt_song_to_instrumental.uploader import authenticate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SLAYR_RELEASES_URL = "https://www.youtube.com/channel/UCivyc3VgQwCqqlr6SlnKQSw/releases"


def main():
    label_config = load_label_config()
    yt_cfg = YouTubeConfig()
    service = authenticate(yt_cfg.client_secrets_file, yt_cfg.token_file)

    logger.info("Scanning slayr Releases tab to extract official discography & track sequences...")
    ydl = yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True})
    res = ydl.extract_info(SLAYR_RELEASES_URL, download=False)

    # Album -> list of track dicts: [{'title': ..., 'id': ..., 'track_num': 1}, ...]
    albums_dict: dict[str, list] = {}

    for e in (res.get("entries") or []):
        pl_url = e.get("url") or e.get("webpage_url")
        if not pl_url:
            continue
        try:
            pl_info = ydl.extract_info(pl_url, download=False)
            album_name = (pl_info.get("title") or "").strip()
            tracks = pl_info.get("entries") or []
            if len(tracks) <= 1:
                # Skip singles (single track releases)
                continue
            logger.info("Discovered album: '%s' (%d tracks)", album_name, len(tracks))
            album_tracks = []
            for idx, track in enumerate(tracks, start=1):
                album_tracks.append({
                    "title": (track.get("title") or "").strip(),
                    "id": track.get("id"),
                    "track_num": idx,
                })
            albums_dict[album_name] = album_tracks
        except Exception as ex:
            logger.warning("Failed to extract release playlist %s: %s", pl_url, ex)

    history = HistoryDB()

    # Query all uploaded slayr tracks from DB
    query = """
    SELECT d.video_id, d.title, d.artist, u.youtube_upload_id, u.privacy
    FROM downloads d
    JOIN uploads u ON d.video_id = u.video_id
    WHERE d.artist LIKE '%slayr%' OR d.channel_name LIKE '%slayr%' OR d.channel_url LIKE '%UCivyc3VgQwCqqlr6SlnKQSw%'
    """
    rows = history._conn.execute(query).fetchall()
    uploaded_tracks = [dict(r) for r in rows]
    logger.info("Found %d uploaded slayr tracks in DB.", len(uploaded_tracks))

    # Helper match function
    def find_upload_id(track_title: str) -> str | None:
        clean_tr = track_title.replace("slayr - ", "").strip().lower()
        for u in uploaded_tracks:
            clean_u = u["title"].replace("slayr - ", "").strip().lower()
            if clean_tr == clean_u or clean_tr in clean_u or clean_u in clean_tr:
                return u["youtube_upload_id"]
        return None

    primary_artist = label_config.artist_aliases.resolve("slayr")

    # Rebuild each album playlist
    for album_name, official_tracks in albums_dict.items():
        # Match uploaded videos for this album
        matched_items = []
        for tr in official_tracks:
            upload_id = find_upload_id(tr["title"])
            if upload_id:
                matched_items.append({
                    "track_num": tr["track_num"],
                    "title": tr["title"],
                    "upload_id": upload_id,
                })

        if not matched_items:
            logger.info("No uploaded tracks found yet for album '%s'; skipping playlist creation.", album_name)
            continue

        # Sort strictly by track_num (1..N)
        matched_items.sort(key=lambda x: x["track_num"])

        logger.info("--- Rebuilding playlist for album '%s' (%d uploaded tracks) ---", album_name, len(matched_items))

        # Get or create album playlist
        playlist_id = get_or_create_album_playlist(
            service=service,
            history=history,
            label_config=label_config,
            artist=primary_artist,
            album=album_name,
            privacy="public",
        )

        # Fetch existing items in playlist to clear them
        res_items = service.playlistItems().list(playlistId=playlist_id, part="snippet", maxResults=50).execute()
        existing_items = res_items.get("items", [])

        # Clear duplicate/out-of-order items
        if len(existing_items) != len(matched_items) or any(existing_items[i]["snippet"]["resourceId"]["videoId"] != matched_items[i]["upload_id"] for i in range(min(len(existing_items), len(matched_items)))):
            logger.info("Clearing %d existing items from playlist %s...", len(existing_items), playlist_id)
            for item in existing_items:
                try:
                    service.playlistItems().delete(id=item["id"]).execute()
                except Exception as ex:
                    logger.warning("Failed to delete item %s: %s", item["id"], ex)

            logger.info("Inserting %d tracks into playlist %s in strict 1..N track sequence...", len(matched_items), playlist_id)
            for m in matched_items:
                logger.info("Adding Track %2d: '%s' (Upload ID: %s)...", m["track_num"], m["title"], m["upload_id"])
                body = {
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": m["upload_id"],
                        },
                    },
                }
                try:
                    service.playlistItems().insert(part="snippet", body=body).execute()
                except Exception as ex:
                    logger.error("Failed to insert video %s into playlist %s: %s", m["upload_id"], playlist_id, ex)
        else:
            logger.info("Playlist %s is already perfectly in order (%d tracks)!", playlist_id, len(matched_items))

    history.close()
    logger.info("All slayr album playlists audited and rebuilt successfully!")


if __name__ == "__main__":
    main()
