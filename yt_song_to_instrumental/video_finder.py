import logging
import re
from pathlib import Path

import yt_dlp

from yt_song_to_instrumental.constants import SHORT_DURATION_SECONDS
from yt_song_to_instrumental.downloader import download_source_video
from yt_song_to_instrumental.video_detector import detect_if_music_video

logger = logging.getLogger(__name__)

_NEGATIVE_KEYWORDS = (
    "audio",
    "official audio",
    "visualizer",
    "official visualizer",
    "lyric video",
    "lyrics",
    "reaction",
    "reacting",
    "review",
    "reviewing",
    "cover",
    "type beat",
    "remake",
    "tutorial",
    "how to",
    "live at",
    "live in",
    "live performance",
    "1 hour",
    "10 hours",
    "10 hour",
    "slowed",
    "sped up",
    "nightcore",
    "daycore",
    "instrumental",
    "karaoke",
    "guitar",
    "piano",
    "drum",
    "behind the scenes",
    "interview",
    "podcast",
    "mashup",
    "tiktok",
    "teaser",
    "snippet",
    "432hz",
    "8d audio",
    "bass boosted",
)

_channel_video_cache: dict[str, list[dict]] = {}


def _tokenize(text: str) -> list[str]:
    # Extract alphanumeric word tokens lowercased
    return [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", text) if len(w) > 1]


def get_channel_videos(channel_url: str) -> list[dict]:
    """Retrieve and cache all video entries for a specific YouTube channel URL."""
    target_url = channel_url.strip()
    if not target_url.endswith("/videos") and not target_url.endswith("/releases"):
        target_url = target_url.rstrip("/") + "/videos"

    if target_url in _channel_video_cache:
        return _channel_video_cache[target_url]

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        logger.info("Fetching video list from official video channel: %s", target_url)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(target_url, download=False)
            entries = res.get("entries", []) or []
            _channel_video_cache[target_url] = entries
            logger.info("Indexed %d videos from official channel %s", len(entries), target_url)
            return entries
    except Exception as e:
        logger.warning("Failed to fetch videos from channel %s: %s", target_url, e)
        return []


def search_channel_candidates(
    video_channel_url: str,
    track_title: str,
    expected_duration: float | None = None,
) -> list[dict]:
    """Search for music video candidates directly within an artist's official channel."""
    entries = get_channel_videos(video_channel_url)
    if not entries:
        return []

    clean_title = re.sub(r"\([^)]*\)", "", track_title).strip()
    title_tokens = set(_tokenize(clean_title))
    if not title_tokens:
        return []

    candidates = []
    for entry in entries:
        if not entry:
            continue
        vid_id = entry.get("id")
        cand_title = entry.get("title") or ""
        cand_dur = entry.get("duration")

        if not vid_id or not cand_title:
            continue

        lower_cand = cand_title.lower()

        # 1. Negative keyword filter
        if any(neg in lower_cand for neg in _NEGATIVE_KEYWORDS):
            continue

        # 2. Duration filter
        if expected_duration is not None and cand_dur is not None:
            cand_dur_f = float(cand_dur)
            max_allowed_diff = max(35.0, expected_duration * 0.35)
            if abs(cand_dur_f - expected_duration) > max_allowed_diff:
                continue

        # 3. Token check: Title tokens should match
        cand_tokens = set(_tokenize(cand_title))
        if title_tokens.issubset(cand_tokens) or (len(title_tokens & cand_tokens) >= max(1, len(title_tokens) - 1)):
            priority = 0
            if "official music video" in lower_cand or "official video" in lower_cand:
                priority = 2
            elif "music video" in lower_cand or "video" in lower_cand:
                priority = 1

            candidates.append({
                "id": vid_id,
                "title": cand_title,
                "duration": cand_dur,
                "priority": priority,
            })

    # Sort so official music videos are evaluated first
    candidates.sort(key=lambda x: x["priority"], reverse=True)
    return candidates


def search_music_video_candidates(
    artist: str,
    track_title: str,
    expected_duration: float | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Search YouTube globally for potential official music video candidates."""
    clean_title = re.sub(r"\([^)]*\)", "", track_title).strip()
    query = f"ytsearch{max_results}:{artist} {clean_title} official video"

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(query, download=False)
    except Exception as e:
        logger.warning("YouTube search failed for '%s': %s", query, e)
        return []

    if not res or not res.get("entries"):
        return []

    title_tokens = set(_tokenize(clean_title))
    candidates = []

    for entry in res.get("entries", []):
        if not entry:
            continue
        vid_id = entry.get("id")
        cand_title = entry.get("title") or ""
        cand_dur = entry.get("duration")
        cand_uploader = entry.get("uploader") or ""

        if not vid_id or not cand_title:
            continue

        lower_cand = cand_title.lower()

        # 1. Negative keyword filter
        if any(neg in lower_cand for neg in _NEGATIVE_KEYWORDS):
            continue

        # 2. Duration filter
        if expected_duration is not None and cand_dur is not None:
            cand_dur_f = float(cand_dur)
            max_allowed_diff = max(35.0, expected_duration * 0.35)
            if abs(cand_dur_f - expected_duration) > max_allowed_diff:
                continue

        # 3. Token check
        cand_tokens = set(_tokenize(cand_title))
        if title_tokens and not (title_tokens & cand_tokens):
            continue

        candidates.append({
            "id": vid_id,
            "title": cand_title,
            "duration": cand_dur,
            "uploader": cand_uploader,
        })

    return candidates


def find_and_verify_music_video(
    artist: str,
    track_title: str,
    tmp_dir: Path,
    expected_duration: float | None = None,
    start_time: float = 0.0,
    video_channel_url: str | None = None,
) -> tuple[Path | None, float]:
    """Find, download, and motion-verify an official music video for a track.
    
    If video_channel_url is provided, searches the artist's official video channel
    first. Falls back to global YouTube search if not found.
    """
    candidates = []
    if video_channel_url:
        candidates = search_channel_candidates(
            video_channel_url, track_title, expected_duration=expected_duration
        )

    if not candidates:
        candidates = search_music_video_candidates(
            artist, track_title, expected_duration=expected_duration, max_results=5
        )

    if not candidates:
        logger.info("No candidate music videos found for: %s — %s", artist, track_title)
        return None, 0.0

    for cand in candidates:
        cand_id = cand["id"]
        cand_title = cand["title"]
        logger.info("Evaluating candidate music video for %s: '%s' (%s)", track_title, cand_title, cand_id)

        video_path = download_source_video(cand_id, tmp_dir)
        if not video_path or not video_path.exists():
            continue

        is_mv, motion_diff = detect_if_music_video(
            video_path, start_time=start_time, duration=SHORT_DURATION_SECONDS
        )

        if is_mv:
            logger.info(
                "Verified genuine music video for %s: '%s' (motion diff=%.2f)",
                track_title,
                cand_title,
                motion_diff,
            )
            return video_path, motion_diff

        logger.info(
            "Candidate '%s' failed motion check (diff=%.2f < threshold); rejecting",
            cand_title,
            motion_diff,
        )
        try:
            if video_path.exists():
                video_path.unlink()
        except Exception:
            pass

    return None, 0.0
