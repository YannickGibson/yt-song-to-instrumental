import logging
import re
import sqlite3
from pathlib import Path

from yt_song_to_instrumental.config import YouTubeConfig
from yt_song_to_instrumental.uploader import authenticate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def clean_video_title(title: str) -> str:
    # 1. Strip leading '<Artist> - Topic — ' or '<Artist> - Topic - '
    t = re.sub(
        r"^([a-zA-Z0-9_\$]+)\s*[\-–—]\s*topic\s*[\-–—]\s*",
        r"\1 — ",
        title,
        flags=re.IGNORECASE,
    )
    # 2. Fix redundant (feat. <Artist>) if primary artist matches feature
    m = re.match(
        r"^(.+?)\s+—\s+(.+?)\s+\(feat\.\s*(.+?)\)\s+\(Instrumental\)$",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        primary = m.group(1).strip()
        track = m.group(2).strip()
        feats = [f.strip() for f in re.split(r"\s*(?:,|&)\s*", m.group(3)) if f.strip()]
        clean_feats = [f for f in feats if f.lower() != primary.lower()]
        if clean_feats:
            return f"{primary} — {track} (feat. {' & '.join(clean_feats)}) (Instrumental)"
        else:
            return f"{primary} — {track} (Instrumental)"
    return t


def get_playlist_item_video_ids(service, playlist_id: str) -> set[str]:
    video_ids = set()
    next_page = None
    try:
        while True:
            res = service.playlistItems().list(
                playlistId=playlist_id,
                part="snippet",
                maxResults=50,
                pageToken=next_page,
            ).execute()
            for item in res.get("items", []):
                vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
                if vid:
                    video_ids.add(vid)
            next_page = res.get("nextPageToken")
            if not next_page:
                break
    except Exception as e:
        logger.warning("Could not list playlist items for %s: %s", playlist_id, e)
    return video_ids


def get_playlist_item_records(service, playlist_id: str) -> list[dict]:
    items = []
    next_page = None
    try:
        while True:
            res = service.playlistItems().list(
                playlistId=playlist_id,
                part="snippet",
                maxResults=50,
                pageToken=next_page,
            ).execute()
            for item in res.get("items", []):
                items.append(item)
            next_page = res.get("nextPageToken")
            if not next_page:
                break
    except Exception as e:
        logger.warning("Could not list playlist items for %s: %s", playlist_id, e)
    return items



def main():
    yt_cfg = YouTubeConfig()
    service = authenticate(yt_cfg.client_secrets_file, yt_cfg.token_file)

    # -------------------------------------------------------------
    # 1. Update Video Titles on YouTube
    # -------------------------------------------------------------
    logger.info("=== Step 1: Scanning for YouTube video titles with '- Topic' ===")
    ch = service.channels().list(mine=True, part="contentDetails").execute()
    uploads_playlist_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    next_page = None
    updated_videos_count = 0

    while True:
        res = service.playlistItems().list(
            playlistId=uploads_playlist_id,
            part="snippet",
            maxResults=50,
            pageToken=next_page,
        ).execute()

        for item in res.get("items", []):
            snippet = item["snippet"]
            old_title = snippet["title"]
            video_id = snippet["resourceId"]["videoId"]

            if "topic" in old_title.lower():
                new_title = clean_video_title(old_title)
                if new_title != old_title:
                    logger.info("Renaming Video %s:\n  OLD: %s\n  NEW: %s", video_id, old_title, new_title)
                    # Fetch video snippet detail for update
                    v_res = service.videos().list(part="snippet,status", id=video_id).execute()
                    if v_res.get("items"):
                        v_item = v_res["items"][0]
                        v_snippet = v_item["snippet"]
                        v_snippet["title"] = new_title

                        # Clean description hashtags if topic is present
                        if "#rexv2topic" in v_snippet.get("description", ""):
                            v_snippet["description"] = v_snippet["description"].replace("#rexv2topic", "#rexv2")
                        if "#1oneamtopic" in v_snippet.get("description", ""):
                            v_snippet["description"] = v_snippet["description"].replace("#1oneamtopic", "#1oneam")

                        service.videos().update(
                            part="snippet",
                            body={
                                "id": video_id,
                                "snippet": v_snippet,
                            },
                        ).execute()
                        updated_videos_count += 1

        next_page = res.get("nextPageToken")
        if not next_page:
            break

    logger.info("Successfully updated %d video titles on YouTube.", updated_videos_count)

    # -------------------------------------------------------------
    # 2. Rename Album Playlists on YouTube
    # -------------------------------------------------------------
    logger.info("=== Step 2: Renaming Album Playlists on YouTube ===")
    album_playlists_to_rename = {
        "PLRwcVVZJkpE4": "rexv2 — ABERRATION (Instrumentals)",
        "PLMUFnMuzCmtc": "rexv2 — Winners Circle (Instrumentals)",
        "PLW-3QKIdAwAY": "1oneam — Sin + (Instrumentals)",
    }

    for playlist_id, new_title in album_playlists_to_rename.items():
        p_res = service.playlists().list(part="snippet", id=playlist_id).execute()
        if p_res.get("items"):
            p_snippet = p_res["items"][0]["snippet"]
            old_title = p_snippet["title"]
            if old_title != new_title:
                logger.info("Renaming Album Playlist %s: '%s' -> '%s'", playlist_id, old_title, new_title)
                p_snippet["title"] = new_title
                service.playlists().update(
                    part="snippet",
                    body={
                        "id": playlist_id,
                        "snippet": p_snippet,
                    },
                ).execute()

    # -------------------------------------------------------------
    # 3. Merge & Clean Artist Playlists on YouTube
    # -------------------------------------------------------------
    logger.info("=== Step 3: Merging & Cleaning Artist Playlists on YouTube ===")
    artist_merges = [
        {"topic_id": "PLYWaECqggo2Q", "target_id": "PLYEhW5Xu010k", "name": "rexv2"},
        {"topic_id": "PLMJreCI_n-zU", "target_id": "PLAt3Qy9g8u38", "name": "1oneam"},
    ]

    for m in artist_merges:
        topic_id = m["topic_id"]
        target_id = m["target_id"]
        artist_name = m["name"]

        target_vids = get_playlist_item_video_ids(service, target_id)
        topic_items = get_playlist_item_records(service, topic_id)
        logger.info("Artist %s: Transferring %d items from %s to %s...", artist_name, len(topic_items), topic_id, target_id)

        for item in topic_items:
            vid = item.get("snippet", {}).get("resourceId", {}).get("videoId")
            if vid and vid not in target_vids:
                logger.info("Adding video %s to %s playlist (%s)...", vid, artist_name, target_id)
                service.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": target_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": vid,
                            },
                        }
                    },
                ).execute()
                target_vids.add(vid)

        logger.info("Deleting topic playlist %s (%s - Topic)...", topic_id, artist_name)
        try:
            service.playlists().delete(id=topic_id).execute()
            logger.info("Deleted playlist %s.", topic_id)
        except Exception as e:
            logger.warning("Could not delete playlist %s: %s", topic_id, e)

    # -------------------------------------------------------------
    # 4. Update Local History Database (data/history.db)
    # -------------------------------------------------------------
    logger.info("=== Step 4: Updating local history database (data/history.db) ===")
    db_path = Path("data/history.db")
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        with conn:
            # Update downloads
            conn.execute("UPDATE downloads SET artist = 'rexv2', channel_name = 'rexv2' WHERE channel_name LIKE '%rexv2%' OR artist LIKE '%rexv2%'")
            conn.execute("UPDATE downloads SET artist = '1oneam', channel_name = '1oneam' WHERE channel_name LIKE '%1oneam%' OR artist LIKE '%1oneam%'")

            # Delete obsolete topic artist and album playlist records
            conn.execute("DELETE FROM playlists WHERE youtube_playlist_id IN ('PLYWaECqggo2Q', 'PLMJreCI_n-zU')")
            conn.execute("DELETE FROM playlists WHERE artist LIKE '%- Topic'")


        conn.close()
        logger.info("Database updated successfully.")

    logger.info("=== Cleanup Complete ===")


if __name__ == "__main__":
    main()

