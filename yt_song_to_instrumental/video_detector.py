import logging
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from yt_song_to_instrumental.constants import (
    SHORT_DEFAULT_MOTION_THRESHOLD,
    SHORT_DIVERSITY_BLUR_RADIUS,
    SHORT_DIVERSITY_MAX_MEDIAN_CORRELATION,
    SHORT_DIVERSITY_MIN_MEDIAN_DIFF,
    SHORT_DIVERSITY_SAMPLE_COUNT,
    SHORT_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)

_AUDIO_INDICATOR_PATTERN = re.compile(
    r"\b(?:official\s+)?(?:audio|visualizer|lyric\s+video|lyrics)\b",
    re.IGNORECASE,
)


def _probe_duration(video_path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        return duration if duration > 0.0 else None
    except (subprocess.CalledProcessError, ValueError):
        logger.warning("Could not probe video duration for diversity check: %s", video_path)
        return None


def _frame_correlation(first: np.ndarray, second: np.ndarray) -> float:
    first_std = float(np.std(first))
    second_std = float(np.std(second))
    if first_std == 0.0 or second_std == 0.0:
        return 1.0 if np.array_equal(first, second) else 0.0
    return float(np.corrcoef(first.reshape(-1), second.reshape(-1))[0, 1])


def _has_sustained_visual_diversity(video_path: Path, tmp_dir: Path) -> tuple[bool, float, float]:
    """Reject fixed-layout visualizers that contain enough effects to look active.

    Sparse frames are sampled across the whole video, heavily blurred to suppress
    particles and small animated overlays, then compared pairwise. Genuine music
    videos normally change composition over time; visualizers keep the same
    low-frequency structure even when parts of the artwork move.
    """
    video_duration = _probe_duration(video_path)
    if video_duration is None:
        return False, 0.0, 1.0

    sample_fps = SHORT_DIVERSITY_SAMPLE_COUNT / video_duration
    out_pattern = tmp_dir / "diversity_%03d.png"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"fps={sample_fps:.8f},scale=160:90",
        "-frames:v", str(SHORT_DIVERSITY_SAMPLE_COUNT),
        "-vsync", "vfr",
        str(out_pattern),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("FFmpeg diversity sampling failed for %s: %s", video_path, exc.stderr)
        return False, 0.0, 1.0

    frames: list[np.ndarray] = []
    for frame_path in sorted(tmp_dir.glob("diversity_*.png")):
        try:
            image = Image.open(frame_path).convert("L").filter(
                ImageFilter.GaussianBlur(radius=SHORT_DIVERSITY_BLUR_RADIUS)
            )
            frames.append(np.array(image, dtype=np.float32))
        except Exception as exc:
            logger.warning("Failed to read diversity frame %s: %s", frame_path, exc)

    if len(frames) < 2:
        return False, 0.0, 1.0

    diffs: list[float] = []
    correlations: list[float] = []
    for index, first in enumerate(frames):
        for second in frames[index + 1:]:
            diffs.append(float(np.mean(np.abs(first - second))))
            correlations.append(_frame_correlation(first, second))

    median_diff = float(np.median(diffs))
    median_correlation = float(np.median(correlations))
    is_diverse = (
        median_diff >= SHORT_DIVERSITY_MIN_MEDIAN_DIFF
        and median_correlation <= SHORT_DIVERSITY_MAX_MEDIAN_CORRELATION
    )
    return is_diverse, median_diff, median_correlation


def detect_if_music_video(
    video_path: Path,
    start_time: float = 0.0,
    duration: float = SHORT_DURATION_SECONDS,
    min_motion_threshold: float = SHORT_DEFAULT_MOTION_THRESHOLD,
    sample_fps: float = 0.5,
    video_title: str = "",
) -> tuple[bool, float]:
    """Detect whether a video is an active music video (moving content)
    vs a static image / simple visualizer.
    
    Extracts sampled frames across `duration` seconds starting at `start_time`
    using a fast single-pass FFmpeg command, and computes consecutive frame
    pixel differences.
    
    Returns:
        tuple[bool, float]: (is_music_video, average_consecutive_motion_diff)
    """
    if video_title and _AUDIO_INDICATOR_PATTERN.search(video_title):
        logger.info(
            "Video title '%s' contains audio/visualizer/lyric indicator; classifying as non-music video",
            video_title,
        )
        return False, 0.0

    if not video_path.exists():
        logger.error("Video file not found for detection: %s", video_path)
        return False, 0.0

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        out_pattern = tmp_dir / "frame_%03d.png"

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(video_path),
            "-vf", f"fps={sample_fps},scale=160:90",
            "-vsync", "vfr",
            str(out_pattern),
        ]

        try:
            logger.info(
                "Sampling frames for music video detection: %s (ss=%.2f, dur=%.2f)",
                video_path.name,
                start_time,
                duration,
            )
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg frame sampling failed for %s: %s", video_path, e.stderr)
            return False, 0.0

        frame_files = sorted(tmp_dir.glob("frame_*.png"))
        if len(frame_files) < 2:
            logger.warning("Fewer than 2 frames extracted for %s; classifying as non-music video", video_path)
            return False, 0.0

        frames: list[np.ndarray] = []
        for f in frame_files:
            try:
                img = Image.open(f).convert("L")
                frames.append(np.array(img, dtype=np.float32))
            except Exception as ex:
                logger.warning("Failed to read sampled frame %s: %s", f, ex)

        if len(frames) < 2:
            return False, 0.0

        diffs = [float(np.mean(np.abs(frames[i] - frames[i - 1]))) for i in range(1, len(frames))]
        max_diff_from_first = float(max(np.mean(np.abs(f - frames[0])) for f in frames[1:]))
        avg_diff = float(np.mean(diffs))

        has_motion = (avg_diff >= min_motion_threshold) or (max_diff_from_first >= min_motion_threshold * 1.5)
        if not has_motion:
            logger.info(
                "Music video detection for %s: is_music_video=False "
                "(avg_consec_diff=%.2f, max_diff=%.2f, threshold=%.2f)",
                video_path.name,
                avg_diff,
                max_diff_from_first,
                min_motion_threshold,
            )
            return False, avg_diff

        has_diversity, median_diff, median_correlation = _has_sustained_visual_diversity(
            video_path, tmp_dir
        )
        is_music_video = has_motion and has_diversity

        logger.info(
            "Music video detection for %s: is_music_video=%s "
            "(avg_consec_diff=%.2f, max_diff=%.2f, diversity_median_diff=%.2f, "
            "diversity_median_correlation=%.3f, threshold=%.2f)",
            video_path.name,
            is_music_video,
            avg_diff,
            max_diff_from_first,
            median_diff,
            median_correlation,
            min_motion_threshold,
        )

        return is_music_video, avg_diff
