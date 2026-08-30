import logging
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from yt_song_to_instrumental.constants import (
    SHORT_DEFAULT_MOTION_THRESHOLD,
    SHORT_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)


def detect_if_music_video(
    video_path: Path,
    start_time: float = 0.0,
    duration: float = SHORT_DURATION_SECONDS,
    min_motion_threshold: float = SHORT_DEFAULT_MOTION_THRESHOLD,
    sample_fps: float = 0.5,
) -> tuple[bool, float]:
    """Detect whether a video is an active music video (moving content)
    vs a static image / simple visualizer.
    
    Extracts sampled frames across `duration` seconds starting at `start_time`
    using a fast single-pass FFmpeg command, and computes consecutive frame
    pixel differences.
    
    Returns:
        tuple[bool, float]: (is_music_video, average_consecutive_motion_diff)
    """
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

        is_music_video = (avg_diff >= min_motion_threshold) or (max_diff_from_first >= min_motion_threshold * 1.5)

        logger.info(
            "Music video detection for %s: is_music_video=%s (avg_consec_diff=%.2f, max_diff=%.2f, threshold=%.2f)",
            video_path.name,
            is_music_video,
            avg_diff,
            max_diff_from_first,
            min_motion_threshold,
        )

        return is_music_video, avg_diff
