import logging
import re
import subprocess
from pathlib import Path

import numpy as np
import yt_dlp
from PIL import Image, ImageFilter

from yt_song_to_instrumental.constants import (
    SHORT_DEFAULT_MOTION_THRESHOLD,
    SHORT_DIVERSITY_BLUR_RADIUS,
    SHORT_DIVERSITY_MAX_MEDIAN_CORRELATION,
    SHORT_DIVERSITY_MIN_MEDIAN_DIFF,
    SHORT_DIVERSITY_SAMPLE_COUNT,
    SHORT_DURATION_SECONDS,
    SHORT_SOURCE_TITLE_PART,
    SHORT_STRUCTURE_FPS, SHORT_STRUCTURE_WIDTH, SHORT_STRUCTURE_HEIGHT,
    SHORT_STRUCTURE_MAX_SECONDS, SHORT_STRUCTURE_TIMEOUT_SECONDS,
    SHORT_PROBE_TIMEOUT_SECONDS, SHORT_STRUCTURE_DECODE_THREADS,
    SHORT_LOOP_WIDTH, SHORT_LOOP_HEIGHT, SHORT_LOOP_MIN_SECONDS,
    SHORT_LOOP_MIN_OVERLAP_SECONDS, SHORT_LOOP_ALIGNMENT_FRAMES,
    SHORT_LOOP_MATCH_CORRELATION, SHORT_LOOP_MIN_COVERAGE, SHORT_LOOP_WINDOWS,
    SHORT_LOOP_MIN_WINDOW_COVERAGE, SHORT_LOOP_MIN_PEAK_MARGIN,
    SHORT_LOOP_EPSILON, SHORT_STRUCTURE_MIN_FRAMES,
    SHORT_STRUCTURE_FRAME_TOLERANCE, SHORT_MOTION_PEAK_MULTIPLIER,
    SHORT_DEFAULT_SAMPLE_FPS, SHORT_REJECT_TITLE_PATTERN,
    SHORT_MUSIC_VIDEO_TITLE_PATTERN,
    SHORT_SOURCE_TITLE_QUOTA_LOG,
    SHORT_PUBLIC_TITLE_OPTIONS, SHORT_PUBLIC_TITLE_KEY, SHORT_PUBLIC_TITLE_ID_KEY,
    SHORT_PUBLIC_TITLE_FALLBACK_LOG, SHORT_PUBLIC_TITLE_FAILED_LOG,
    YOUTUBE_CANONICAL_VIDEO_URL,
)
from yt_song_to_instrumental.youtube_quota import QuotaReserved

logger = logging.getLogger(__name__)

_AUDIO_INDICATOR_PATTERN = re.compile(SHORT_REJECT_TITLE_PATTERN, re.IGNORECASE)
_MUSIC_VIDEO_TITLE_PATTERN = re.compile(SHORT_MUSIC_VIDEO_TITLE_PATTERN, re.IGNORECASE)


def has_rejected_video_label(title: str) -> bool:
    return bool(_AUDIO_INDICATOR_PATTERN.search(title))


def get_public_source_title(video_id: str) -> str | None:
    """Read raw public metadata for the exact source without consuming API quota."""
    try:
        with yt_dlp.YoutubeDL(dict(SHORT_PUBLIC_TITLE_OPTIONS)) as extractor:
            info = extractor.extract_info(YOUTUBE_CANONICAL_VIDEO_URL.format(video_id=video_id), download=False)
        if info and info.get(SHORT_PUBLIC_TITLE_ID_KEY) == video_id:
            title = info.get(SHORT_PUBLIC_TITLE_KEY)
            if isinstance(title, str) and title.strip():
                return title
    except Exception:
        logger.warning(SHORT_PUBLIC_TITLE_FAILED_LOG)
    return None


def has_music_video_label(title: str) -> bool:
    """Require an explicit music-video label without conflicting content labels.

    This is metadata evidence, not visual classification. Publisher membership
    must be checked separately before trusting any source.
    """
    return bool(
        _MUSIC_VIDEO_TITLE_PATTERN.search(title)
        and not _AUDIO_INDICATOR_PATTERN.search(title)
    )

def get_source_video_title(service, video_id: str) -> str | None:
    """Read the unmodified source title; normalized track metadata loses warnings."""
    try:
        response = service.videos().list(part=SHORT_SOURCE_TITLE_PART, id=video_id).execute()
        for item in response["items"]:
            if item["id"] == video_id:
                title = item["snippet"]["title"]
                if isinstance(title, str) and title.strip():
                    return title
    except QuotaReserved:
        logger.info(SHORT_PUBLIC_TITLE_FALLBACK_LOG)
        title = get_public_source_title(video_id)
        if title is not None:
            return title
        logger.warning(SHORT_SOURCE_TITLE_QUOTA_LOG)
    except Exception:
        logger.warning("Source title unavailable; refusing unverified Short source")
    return None


def _probe_duration(video_path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                timeout=SHORT_PROBE_TIMEOUT_SECONDS)
        duration = float(result.stdout.strip())
        return duration if np.isfinite(duration) and duration > 0.0 else None
    except (subprocess.SubprocessError, OSError, ValueError):
        logger.warning("Could not probe video duration for diversity check: %s", video_path)
        return None


def _frame_correlation(first: np.ndarray, second: np.ndarray) -> float:
    first_std = float(np.std(first))
    second_std = float(np.std(second))
    if first_std == 0.0 or second_std == 0.0:
        return 1.0
    return float(np.corrcoef(first.reshape(-1), second.reshape(-1))[0, 1])


def _sample_source(video_path: Path, video_duration: float) -> np.ndarray | None:
    """Decode the entire source once, with bounded memory and a deadline."""
    if video_duration > SHORT_STRUCTURE_MAX_SECONDS:
        logger.warning("Source exceeds automatic screening duration limit; skipping")
        return None
    expected = int(round(video_duration * SHORT_STRUCTURE_FPS))
    cmd = [
        "ffmpeg", "-v", "error", "-threads", str(SHORT_STRUCTURE_DECODE_THREADS),
        "-i", str(video_path), "-an", "-sn",
        "-vf", f"fps={SHORT_STRUCTURE_FPS},scale={SHORT_STRUCTURE_WIDTH}:{SHORT_STRUCTURE_HEIGHT},format=gray",
        "-frames:v", str(expected + SHORT_STRUCTURE_FRAME_TOLERANCE),
        "-f", "rawvideo", "pipe:1",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True,
                                timeout=SHORT_STRUCTURE_TIMEOUT_SECONDS)
        frames = np.frombuffer(result.stdout, dtype=np.uint8).reshape(
            -1, SHORT_STRUCTURE_HEIGHT, SHORT_STRUCTURE_WIDTH)
    except (subprocess.SubprocessError, OSError, ValueError):
        logger.warning("Full-source screening failed; skipping Short", exc_info=True)
        return None
    if (len(frames) < SHORT_STRUCTURE_MIN_FRAMES
            or abs(len(frames) - expected) > SHORT_STRUCTURE_FRAME_TOLERANCE
            or len(frames) >= expected + SHORT_STRUCTURE_FRAME_TOLERANCE):
        logger.warning("Incomplete or inconsistent full-source sample; skipping Short")
        return None
    return frames


def _loop_evidence(frames: np.ndarray) -> tuple[bool, float, float]:
    """Find recurring sequences, not isolated similar shots.

    Scan every lag from three seconds through half the source. Nearby sample
    alignment tolerates non-integer periods. Require matches throughout all
    quarters of the overlap AND a peak over incidental background similarity.
    O(N * L * P), where P is a fixed 32x18 fingerprint and L <= N/2;
    N is capped by the source-duration limit. No N-by-N matrix is retained.
    """
    fingerprints = np.stack([
        np.asarray(Image.fromarray(frame).resize(
            (SHORT_LOOP_WIDTH, SHORT_LOOP_HEIGHT), Image.Resampling.BILINEAR),
            dtype=np.float32).reshape(-1)
        for frame in frames
    ])
    fingerprints -= fingerprints.mean(axis=1, keepdims=True)
    norms = np.linalg.norm(fingerprints, axis=1, keepdims=True)
    fingerprints /= np.maximum(norms, SHORT_LOOP_EPSILON)
    min_lag = int(SHORT_LOOP_MIN_SECONDS * SHORT_STRUCTURE_FPS)
    min_overlap = int(SHORT_LOOP_MIN_OVERLAP_SECONDS * SHORT_STRUCTURE_FPS)
    tolerance = SHORT_LOOP_ALIGNMENT_FRAMES
    max_lag = min(len(frames) // 2, len(frames) - min_overlap - tolerance)
    scores = []
    for lag in range(min_lag, max_lag + 1):
        count = len(frames) - lag - tolerance
        first = fingerprints[:count]
        correlations = np.maximum.reduce([
            np.einsum("ij,ij->i", first, fingerprints[lag + shift:lag + shift + count])
            for shift in range(-tolerance, tolerance + 1)
        ])
        matches = correlations >= SHORT_LOOP_MATCH_CORRELATION
        coverage = float(np.mean(matches))
        spread = min(float(np.mean(window)) for window in np.array_split(matches, SHORT_LOOP_WINDOWS))
        scores.append((coverage, lag, spread))
    if not scores:
        return False, 0.0, 0.0
    background = float(np.median([score[0] for score in scores]))
    best = max(scores)
    qualified = [score for score in scores
                 if score[0] >= SHORT_LOOP_MIN_COVERAGE
                 and score[2] >= SHORT_LOOP_MIN_WINDOW_COVERAGE
                 and score[0] - background >= SHORT_LOOP_MIN_PEAK_MARGIN]
    if qualified:
        # Prefer the shortest strong peak, not a multiple of the same period.
        best = min(qualified, key=lambda score: score[1])
    return bool(qualified), best[1] / SHORT_STRUCTURE_FPS, best[0]


def _visual_diversity(frames: np.ndarray) -> tuple[bool, float, float]:
    indices = np.linspace(0, len(frames) - 1, min(SHORT_DIVERSITY_SAMPLE_COUNT, len(frames)), dtype=int)
    samples = [np.asarray(Image.fromarray(frames[index]).filter(
        ImageFilter.GaussianBlur(radius=SHORT_DIVERSITY_BLUR_RADIUS)), dtype=np.float32)
        for index in indices]
    diffs = []
    correlations = []
    for index, first in enumerate(samples):
        for second in samples[index + 1:]:
            diffs.append(float(np.mean(np.abs(first - second))))
            correlations.append(_frame_correlation(first, second))
    median_diff = float(np.median(diffs))
    median_correlation = float(np.median(correlations))
    return (median_diff >= SHORT_DIVERSITY_MIN_MEDIAN_DIFF
            and median_correlation <= SHORT_DIVERSITY_MAX_MEDIAN_CORRELATION,
            median_diff, median_correlation)


def detect_if_music_video(
    video_path: Path,
    start_time: float = 0.0,
    duration: float = SHORT_DURATION_SECONDS,
    min_motion_threshold: float = SHORT_DEFAULT_MOTION_THRESHOLD,
    sample_fps: float = SHORT_DEFAULT_SAMPLE_FPS,
    video_title: str = "",
) -> tuple[bool, float]:
    """Screen moving sources for Shorts eligibility, not semantic content safety.

    Reuse one full-source decode for local motion, composition, and sequence
    repetition. Missing/failed/over-limit analysis fails closed. A positive
    result is heuristic music-video eligibility, not proof of safe imagery.
    """
    if video_title and _AUDIO_INDICATOR_PATTERN.search(video_title):
        logger.info("Source title contains an excluded format; skipping Short")
        return False, 0.0
    if (not video_path.is_file() or not all(np.isfinite(value) for value in
            (start_time, duration, min_motion_threshold, sample_fps))
            or start_time < 0 or duration <= 0 or sample_fps <= 0):
        return False, 0.0
    video_duration = _probe_duration(video_path)
    if video_duration is None:
        return False, 0.0
    frames = _sample_source(video_path, video_duration)
    if frames is None:
        return False, 0.0
    stride = max(1, int(round(SHORT_STRUCTURE_FPS / sample_fps)))
    first = int(start_time * SHORT_STRUCTURE_FPS)
    last = int((start_time + duration) * SHORT_STRUCTURE_FPS)
    local = frames[first:last:stride].astype(np.float32)
    if len(local) < SHORT_STRUCTURE_MIN_FRAMES:
        return False, 0.0
    avg_diff = float(np.mean(np.abs(np.diff(local, axis=0))))
    peak_diff = float(np.max(np.mean(np.abs(local[1:] - local[0]), axis=(1, 2))))
    has_motion = (avg_diff >= min_motion_threshold
                  or peak_diff >= min_motion_threshold * SHORT_MOTION_PEAK_MULTIPLIER)
    if not has_motion:
        logger.info("Source lacks substantial clip motion; skipping Short")
        return False, avg_diff
    repeated, period, coverage = _loop_evidence(frames)
    diverse, median_diff, median_corr = _visual_diversity(frames)
    eligible = bool(diverse and not repeated)
    logger.info(
        "Music-video screening: eligible=%s repeated=%s period_seconds=%.2f "
        "match_coverage=%.3f motion=%.2f diversity_diff=%.2f diversity_corr=%.3f frames=%d",
        eligible, repeated, period, coverage, avg_diff, median_diff, median_corr, len(frames))
    return eligible, avg_diff
