import logging
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yt_dlp

from yt_song_to_instrumental.constants import (
    SHORT_DEFAULT_START_SECONDS,
    SHORT_DURATION_SECONDS,
    VIDEO_CHANNEL_INDEX_ERROR_LOG,
    VIDEO_CHANNEL_MISSING_LOG,
    VIDEO_CHANNEL_RESPONSE_ERROR,
    VIDEO_CHANNEL_SCREENING_LOG,
    VIDEO_CHANNEL_PASSED_LOG,
    VIDEO_CHANNEL_REJECTED_LOG,
    VIDEO_CHANNEL_TAB,
    VIDEO_CHANNEL_TABS,
    VIDEO_MATCH_DASH_PATTERN,
    VIDEO_MATCH_DEFAULT_ARTIST,
    VIDEO_MATCH_DURATION_TOLERANCE_FRACTION,
    VIDEO_MATCH_DURATION_TOLERANCE_SECONDS,
    VIDEO_MATCH_PARENS_PATTERN,
    VIDEO_MATCH_TOKEN_PATTERN,
    YOUTUBE_CANONICAL_VIDEO_URL,
)
from yt_song_to_instrumental.downloader import download_source_video
from yt_song_to_instrumental.video_detector import detect_if_music_video, has_music_video_label, has_rejected_video_label

logger = logging.getLogger(__name__)

_channel_video_cache: dict[str, list[dict]] = {}


class VideoChannelUnavailable(RuntimeError):
    """A channel could not be inspected; keep its pending Shorts retryable."""


def _tokenize(text: str) -> list[str]:
    return re.findall(VIDEO_MATCH_TOKEN_PATTERN, text.casefold())


def _song_title(title: str, artist: str) -> str:
    cleaned = re.sub(VIDEO_MATCH_PARENS_PATTERN, VIDEO_MATCH_DEFAULT_ARTIST, title).strip()
    parts = re.split(VIDEO_MATCH_DASH_PATTERN, cleaned, maxsplit=1)
    if len(parts) > 1 and _tokenize(parts[0]) == _tokenize(artist):
        return parts[1]
    return cleaned


def get_channel_videos(channel_url: str) -> list[dict]:
    """Index only the approved channel's Videos tab, never global recommendations."""
    parsed = urlsplit(channel_url.strip())
    path = parsed.path.rstrip("/")
    for tab in VIDEO_CHANNEL_TABS:
        if path.endswith(tab):
            path = path[:-len(tab)]
            break
    target_url = urlunsplit((parsed.scheme, parsed.netloc, path + VIDEO_CHANNEL_TAB,
                            VIDEO_MATCH_DEFAULT_ARTIST, VIDEO_MATCH_DEFAULT_ARTIST))
    if target_url in _channel_video_cache:
        return _channel_video_cache[target_url]
    try:
        with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True, "no_warnings": True}) as ydl:
            result = ydl.extract_info(target_url, download=False)
            if not result or result.get("entries") is None:
                raise VideoChannelUnavailable(VIDEO_CHANNEL_RESPONSE_ERROR)
            entries = list(result["entries"])
            _channel_video_cache[target_url] = entries
            return entries
    except Exception as error:
        logger.warning(VIDEO_CHANNEL_INDEX_ERROR_LOG, channel_url, error)
        raise VideoChannelUnavailable(VIDEO_CHANNEL_RESPONSE_ERROR) from error


def is_trusted_music_video(video_id: str, title: str, channel_url: str | None, *, requested_source: bool = False) -> bool:
    """Require approved-channel membership and normally explicit video labeling.

    Names and words such as 'official' alone do not establish who uploaded it.
    Missing channel evidence fails closed, including for a direct release source.
    An explicitly requested source may omit the music-video label; negative
    labels and the subsequent structural screening still apply.
    """
    if not channel_url or not title.strip() or has_rejected_video_label(title):
        return False
    if not requested_source and not has_music_video_label(title):
        return False
    return any(entry and entry.get("id") == video_id for entry in get_channel_videos(channel_url))


def search_channel_candidates(
    video_channel_url: str,
    track_title: str,
    expected_duration: float | None = None,
    artist: str = VIDEO_MATCH_DEFAULT_ARTIST,
) -> list[dict]:
    """Find explicitly labeled music videos within the approved channel only."""
    title_tokens = set(_tokenize(_song_title(track_title, artist)))
    if not title_tokens:
        return []
    candidates = []
    for entry in get_channel_videos(video_channel_url):
        if not entry:
            continue
        candidate_id = entry.get("id")
        candidate_title = entry.get("title") or VIDEO_MATCH_DEFAULT_ARTIST
        candidate_duration = entry.get("duration")
        if not candidate_id or not has_music_video_label(candidate_title):
            continue
        if not title_tokens.issubset(set(_tokenize(candidate_title))):
            continue
        if expected_duration is not None and candidate_duration is not None:
            tolerance = max(VIDEO_MATCH_DURATION_TOLERANCE_SECONDS,
                            expected_duration * VIDEO_MATCH_DURATION_TOLERANCE_FRACTION)
            if abs(float(candidate_duration) - expected_duration) > tolerance:
                continue
        candidates.append(entry)
    return candidates


def find_and_verify_music_video(
    artist: str,
    track_title: str,
    tmp_dir: Path,
    expected_duration: float | None = None,
    start_time: float = SHORT_DEFAULT_START_SECONDS,
    video_channel_url: str | None = None,
) -> tuple[Path | None, float, str | None]:
    """Screen videos from the approved channel; never fall back to unrelated uploads."""
    if not video_channel_url:
        logger.info(VIDEO_CHANNEL_MISSING_LOG, track_title)
        return None, SHORT_DEFAULT_START_SECONDS, None
    candidates = search_channel_candidates(
        video_channel_url, track_title, expected_duration=expected_duration, artist=artist,
    )
    for candidate in candidates:
        candidate_id = candidate["id"]
        candidate_title = candidate["title"]
        logger.info(VIDEO_CHANNEL_SCREENING_LOG,
                    track_title, candidate_title, candidate_id)
        video_path = download_source_video(candidate_id, tmp_dir)
        if not video_path or not video_path.exists():
            continue
        eligible, motion_diff = detect_if_music_video(
            video_path, start_time=start_time, duration=SHORT_DURATION_SECONDS,
            video_title=candidate_title,
        )
        if eligible:
            logger.info(VIDEO_CHANNEL_PASSED_LOG, candidate_id)
            return video_path, motion_diff, YOUTUBE_CANONICAL_VIDEO_URL.format(video_id=candidate_id)
        logger.info(VIDEO_CHANNEL_REJECTED_LOG, candidate_id)
        video_path.unlink(missing_ok=True)
    return None, SHORT_DEFAULT_START_SECONDS, None
