import logging
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from yt_song_to_instrumental.constants import (
    YTDLP_FORMAT,
    YTDLP_RETRIES,
)
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.metadata import strip_title_parentheticals, strip_topic_suffix, version_priority
from yt_song_to_instrumental.music_metadata import lookup_album_index, lookup_track, lookup_video_date

logger = logging.getLogger(__name__)

# Tab paths yt-dlp surfaces for a YouTube channel handle. We only process Videos
# or Releases (when tab="releases" is configured); Live and Shorts are dropped.
_VIDEOS_TAB_SUFFIX = "/videos"
_RELEASES_TAB_SUFFIX = "/releases"
_TAB_SUFFIXES = ("/videos", "/streams", "/shorts", "/playlists", "/community", "/featured", "/releases")
_MAX_ENUM_DEPTH = 2



@dataclass
class DownloadedTrack:
    video_id: str
    url: str
    title: str
    artist: str
    album: str
    channel_name: str
    channel_url: str
    audio_path: Path
    thumbnail_path: Path


def _best_thumbnail_url(info: dict) -> str:
    thumbnails = info.get("thumbnails", [])
    if not thumbnails:
        return info.get("thumbnail", "")
    best = max(thumbnails, key=lambda t: t.get("preference", 0))
    return best.get("url", "")


def _resolve_metadata(info: dict, ytmusic) -> dict:
    """Combine yt-dlp info with YTMusic data using the source priority chain.

    For each field the order is: YTMusic → yt-dlp typed field → fallback. YTMusic
    is the authoritative source when it has the exact video (the videoId match
    is enforced in lookup_track), because it carries the full collaborator list
    that yt-dlp's `artist` field omits for many music-channel uploads.
    """
    if ytmusic is not None and ytmusic.title:
        title = ytmusic.title
    elif info.get("track"):
        title = info["track"]
    else:
        title = info.get("title") or "Unknown"
    title = strip_title_parentheticals(title) or title

    if ytmusic is not None and ytmusic.artists:
        artist = ", ".join(strip_topic_suffix(a) for a in ytmusic.artists)
        all_artists = [strip_topic_suffix(a) for a in ytmusic.artists]
    elif info.get("artist"):
        clean_art = strip_topic_suffix(info["artist"])
        artist = clean_art
        all_artists = [clean_art]
    else:
        raw_art = info.get("uploader") or "Unknown"
        clean_art = strip_topic_suffix(raw_art)
        artist = clean_art
        all_artists = [clean_art]

    if ytmusic is not None and ytmusic.album:
        album = ytmusic.album
    elif info.get("album"):
        album = info["album"]
    elif info.get("_album_title"):
        album = info["_album_title"]
    else:
        album = ""

    raw_channel = info.get("channel") or info.get("uploader") or ""

    return {
        "video_id": info["id"],
        "url": info.get("webpage_url") or info.get("url") or "",
        "title": title,
        "artist": artist,
        "album": album,
        "channel_name": strip_topic_suffix(raw_channel),
        "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
        "_ytmusic_hit": ytmusic is not None,
        "_all_artists": all_artists,
    }


def fetch_preview_metadata(video_id: str, fallback_title: str, fallback_uploader: str, fallback_album: str = "") -> dict:
    """Lightweight metadata for dry-run preview — YTMusic only, no yt-dlp full
    extract. Falls back to flat-enumeration title/uploader when YTMusic misses.
    """
    ytmusic = lookup_track(video_id)
    if ytmusic is not None and ytmusic.title:
        title = ytmusic.title
    else:
        title = fallback_title or "Unknown"
    title = strip_title_parentheticals(title) or title
    if ytmusic is not None and ytmusic.artists:
        artist = ", ".join(strip_topic_suffix(a) for a in ytmusic.artists)
        all_artists = [strip_topic_suffix(a) for a in ytmusic.artists]
    else:
        artist = strip_topic_suffix(fallback_uploader) or "Unknown"
        all_artists = [artist]
    album = ytmusic.album if (ytmusic is not None and ytmusic.album) else fallback_album
    return {
        "video_id": video_id,
        "title": title,
        "artist": artist,
        "album": album,
        "_ytmusic_hit": ytmusic is not None,
        "_all_artists": all_artists,
        "_upload_date": lookup_video_date(video_id),
    }



def _is_tabbed_channel(playlist_info: dict) -> bool:
    entries = playlist_info.get("entries") or []
    if not entries:
        return False
    for e in entries:
        if not isinstance(e, dict):
            continue
        wp = e.get("webpage_url") or ""
        if any(wp.endswith(suffix) for suffix in _TAB_SUFFIXES):
            return True
    return False


def _entry_passes_after_date(entry: dict, after_date: str | None) -> bool:
    if after_date is None:
        return True
    upload_date = entry.get("upload_date")
    if not upload_date:
        # Flat extraction often omits upload_date; let it through and let a
        # downstream deep fetch (or yt-dlp's own filter during download) handle it.
        return True
    return upload_date >= after_date


def enumerate_videos(url: str, after_date: str | None = None, tab: str = "videos") -> list[dict]:
    """Return flat yt_dlp entries representing the videos this URL implies.

    - Single video URL → one entry.
    - Playlist URL → the playlist's entries.
    - Channel handle (tabbed) → entries from the specified tab (videos or releases).

    Each returned entry is stamped with `_source_channel` (str), the top-level
    channel/uploader/title from yt-dlp — used downstream as the primary-artist
    hint for video title rendering.

    Applies a client-side after_date filter as a safety net when yt-dlp surfaces
    upload_date in flat mode.
    """
    tab_name = (tab or "videos").strip().lower()
    if tab_name not in ("videos", "releases"):
        tab_name = "videos"
    target_tab_suffix = _RELEASES_TAB_SUFFIX if tab_name == "releases" else _VIDEOS_TAB_SUFFIX

    if tab_name == "releases":
        if url.endswith("/videos"):
            url = url[:-7] + "/releases"
        elif not url.endswith("/releases") and ("/channel/" in url or "/@" in url or "/user/" in url or "music.youtube.com" in url):
            url = url.rstrip("/") + "/releases"

    extract_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
    }
    if after_date:
        extract_opts["dateafter"] = after_date
    try:
        with yt_dlp.YoutubeDL(extract_opts) as ydl:
            playlist_info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        logger.warning("Failed to extract info from %s: %s", url, e)
        return []

    if playlist_info is None:
        logger.error("Failed to extract info from %s", url)
        return []

    # Capture channel info from top-level; we'll re-capture after descent below
    # because the Videos-tab playlist often has more specific fields populated.
    source_channel = (
        playlist_info.get("channel")
        or playlist_info.get("uploader")
        or playlist_info.get("title")
        or ""
    )
    source_channel_id = (
        playlist_info.get("channel_id")
        or playlist_info.get("uploader_id")
        or ""
    )

    depth = 0
    while _is_tabbed_channel(playlist_info) and depth < _MAX_ENUM_DEPTH:
        target_tab = None
        for e in (playlist_info.get("entries") or []):
            if not isinstance(e, dict):
                continue
            wp = e.get("webpage_url") or ""
            if wp.endswith(target_tab_suffix):
                target_tab = e
                break
        if target_tab is None:
            logger.warning(
                "Tabbed channel at %s has no %s tab; nothing to process",
                url,
                "Releases" if tab_name == "releases" else "Videos",
            )
            return []
        tab_url = target_tab.get("url") or target_tab.get("webpage_url")
        if not tab_url:
            return []
        try:
            with yt_dlp.YoutubeDL({"extract_flat": "in_playlist", "quiet": True, "no_warnings": True}) as ydl2:
                playlist_info = ydl2.extract_info(tab_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            logger.warning("Failed to extract tab info from %s: %s", tab_url, e)
            return []
        if playlist_info is None:
            return []
        depth += 1

    # Prefer the (post-descent) playlist's channel info — it's the most specific
    # — falling back to whatever we captured pre-descent.
    source_channel = (
        playlist_info.get("channel")
        or playlist_info.get("uploader")
        or source_channel
    )
    source_channel_id = (
        playlist_info.get("channel_id")
        or playlist_info.get("uploader_id")
        or source_channel_id
    )

    entries = playlist_info.get("entries") or [playlist_info]
    entries = [e for e in entries if isinstance(e, dict)]

    if tab_name == "releases":
        flattened: list[dict] = []
        for e in entries:
            is_playlist = (
                e.get("_type") in ("playlist", "multi_video")
                or "playlist?list=" in (e.get("url") or e.get("webpage_url") or "")
            )
            if is_playlist:
                pl_url = e.get("url") or e.get("webpage_url")
                if pl_url:
                    try:
                        with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True, "no_warnings": True}) as ydl_pl:
                            pl_info = ydl_pl.extract_info(pl_url, download=False)
                            album_title = (pl_info.get("title") or "") if pl_info else ""
                            if pl_info and pl_info.get("entries"):
                                for child in pl_info["entries"]:
                                    if isinstance(child, dict):
                                        if album_title:
                                            child["_album_title"] = album_title
                                        flattened.append(child)
                    except yt_dlp.utils.DownloadError:
                        pass
            else:
                flattened.append(e)
        if flattened:
            entries = flattened

    if after_date:
        entries = [e for e in entries if _entry_passes_after_date(e, after_date)]
    for e in entries:
        if source_channel:
            e.setdefault("_source_channel", strip_topic_suffix(source_channel))
        if source_channel_id:
            e.setdefault("_source_channel_id", source_channel_id)
    return entries



def dedupe_entries_prefer_audio(entries: list[dict]) -> list[dict]:
    """Drop duplicate uploads of the same track, preferring the audio rip over
    music-video versions (which have abrupt pauses). Key on the parens-stripped
    title alone — within a single source channel that uniquely identifies a
    track.

    When two entries tie on version priority (e.g. two plain uploads of the
    same song, neither marked Audio/Video), the tie is broken by the smaller
    video_id. That keeps the pick deterministic across runs even if yt-dlp's
    channel-enumeration order shifts — otherwise the dedup could flip and
    re-download/re-upload a near-duplicate.
    """
    chosen: dict[str, dict] = {}
    order: list[str] = []
    for entry in entries:
        raw = entry.get("title") or ""
        key = strip_title_parentheticals(raw).strip().lower()
        if not key:
            key = f"__id:{entry.get('id') or ''}"
        existing = chosen.get(key)
        if existing is None:
            chosen[key] = entry
            order.append(key)
            continue
        new_pri = version_priority(raw)
        cur_pri = version_priority(existing.get("title") or "")
        if new_pri < cur_pri:
            chosen[key] = entry
        elif new_pri == cur_pri and (entry.get("id") or "") < (existing.get("id") or ""):
            chosen[key] = entry
    return [chosen[k] for k in order]


def fetch_full_metadata(video_url: str) -> dict | None:
    """Non-downloading deep extract for a single video + YTMusic enrich.

    Used by the real-download path (yt-dlp full extract is needed anyway for the
    audio download). Preview uses fetch_preview_metadata instead and skips the
    yt-dlp call.
    """
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        logger.warning("Full metadata fetch failed for %s: %s", video_url, e)
        return None
    if info is None:
        return None
    ytmusic = lookup_track(info["id"])
    return _resolve_metadata(info, ytmusic)


def download_tracks(
    url: str,
    history: HistoryDB,
    tmp_dir: Path,
    after_date: str | None = None,
    tab: str = "videos",
) -> list[DownloadedTrack]:
    tmp_dir.mkdir(parents=True, exist_ok=True)

    entries = enumerate_videos(url, after_date=after_date, tab=tab)
    raw_count = len(entries)
    entries = dedupe_entries_prefer_audio(entries)
    if raw_count != len(entries):
        logger.info("Dropped %d duplicate uploads (audio version preferred)", raw_count - len(entries))

    # Date filter: yt-dlp's `dateafter` is unreliable for music-channel videos
    # (flat extract surfaces no upload_date, and full-extract dateafter quietly
    # passes everything through), so we look up the date via YTMusic and filter
    # client-side before any expensive yt-dlp download.
    if after_date:
        kept: list[dict] = []
        for entry in entries:
            vid = entry.get("id")
            if not vid:
                kept.append(entry)
                continue
            date = entry.get("upload_date") or lookup_video_date(vid)
            if date and date < after_date:
                continue
            kept.append(entry)
        dropped = len(entries) - len(kept)
        if dropped:
            logger.info("Filtered %d entries by after_date %s", dropped, after_date)
        entries = kept

    source_channel_id = ""
    for e in entries:
        if e.get("_source_channel_id"):
            source_channel_id = e["_source_channel_id"]
            break
    album_index = lookup_album_index(source_channel_id)

    download_opts = {
        "format": YTDLP_FORMAT,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "writethumbnail": True,
        "retries": YTDLP_RETRIES,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
    }

    results: list[DownloadedTrack] = []

    for entry in entries:
        if entry is None:
            continue

        video_id = entry.get("id", "")
        if not video_id:
            continue

        if history.is_downloaded(video_id):
            logger.info("Skipping already downloaded: %s", video_id)
            continue

        logger.info("Downloading: %s", entry.get("title", video_id))

        try:
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                info = ydl.extract_info(entry.get("url", entry.get("webpage_url", "")), download=True)
        except yt_dlp.utils.DownloadError as e:
            logger.error("Failed to download %s: %s", video_id, e)
            continue

        if info is None:
            continue

        if entry.get("_album_title") and not info.get("album"):
            info["_album_title"] = entry["_album_title"]

        meta = _resolve_metadata(info, lookup_track(info["id"]))
        album = meta["album"] or album_index.album_for(meta["title"])
        # A single-track "album" is a single, not an album — clearing it here
        # means no album playlist gets created for it downstream.
        meta["album"] = "" if album_index.is_single(album, meta["title"]) else album
        audio_path = tmp_dir / f"{video_id}.wav"

        thumbnail_path = _find_thumbnail(tmp_dir, video_id)

        history.record_download(
            video_id=meta["video_id"],
            url=meta["url"],
            title=meta["title"],
            artist=meta["artist"],
            album=meta["album"],
            channel_name=meta["channel_name"],
            channel_url=meta["channel_url"],
            audio_path=str(audio_path),
            thumbnail_path=str(thumbnail_path),
        )

        results.append(DownloadedTrack(
            video_id=meta["video_id"],
            url=meta["url"],
            title=meta["title"],
            artist=meta["artist"],
            album=meta["album"],
            channel_name=meta["channel_name"],
            channel_url=meta["channel_url"],
            audio_path=audio_path,
            thumbnail_path=thumbnail_path,
        ))

    return results


def _find_thumbnail(tmp_dir: Path, video_id: str) -> Path:
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        path = tmp_dir / f"{video_id}{ext}"
        if path.exists():
            return path
    return Path("")


def download_source_video(url_or_video_id: str, tmp_dir: Path) -> Path | None:
    """Download source video stream for Short rendering."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    video_id = url_or_video_id
    if "youtube.com" in url_or_video_id or "youtu.be" in url_or_video_id:
        target_url = url_or_video_id
    else:
        target_url = f"https://www.youtube.com/watch?v={url_or_video_id}"

    for ext in (".mp4", ".mkv", ".webm"):
        cand = tmp_dir / f"video_{video_id}{ext}"
        if cand.exists():
            return cand
        cand_raw = tmp_dir / f"{video_id}{ext}"
        if cand_raw.exists() and cand_raw.suffix != ".wav":
            return cand_raw

    outtmpl = str(tmp_dir / "video_%(id)s.%(ext)s")
    opts = {
        "format": "bestvideo[height<=1080]/bestvideo[height<=720]/best",
        "outtmpl": outtmpl,
        "retries": YTDLP_RETRIES,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            if info:
                vid = info.get("id", video_id)
                for ext in (".mp4", ".mkv", ".webm"):
                    p = tmp_dir / f"video_{vid}{ext}"
                    if p.exists():
                        return p
    except Exception as e:
        logger.error("Failed to download source video for %s: %s", url_or_video_id, e)
        return None
    return None


def download_track_audio(url_or_video_id: str, tmp_dir: Path) -> Path | None:
    """Download single track audio WAV file for separation."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    video_id = url_or_video_id
    if "youtube.com" in url_or_video_id or "youtu.be" in url_or_video_id:
        target_url = url_or_video_id
    else:
        target_url = f"https://www.youtube.com/watch?v={url_or_video_id}"

    cand = tmp_dir / f"{video_id}.wav"
    if cand.exists():
        return cand

    download_opts = {
        "format": YTDLP_FORMAT,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "writethumbnail": False,
        "retries": YTDLP_RETRIES,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
    }
    try:
        with yt_dlp.YoutubeDL(download_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            if info:
                vid = info.get("id", video_id)
                p = tmp_dir / f"{vid}.wav"
                if p.exists():
                    return p
    except Exception as e:
        logger.error("Failed to download audio for %s: %s", url_or_video_id, e)
        return None
    return None

