import logging
import subprocess
from pathlib import Path

from yt_song_to_instrumental.constants import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
    SHORT_BAR_HEIGHT,
    SHORT_CONTENT_HEIGHT,
    SHORT_DURATION_SECONDS,
    SHORT_PRESET,
    SHORT_VIDEO_CRF,
    SHORT_VIDEO_HEIGHT,
    SHORT_VIDEO_WIDTH,
    VIDEO_CODEC,
    VIDEO_CRF,
    VIDEO_PIXEL_FORMAT,
)

logger = logging.getLogger(__name__)


def render_video(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", VIDEO_CODEC,
        "-tune", "stillimage",
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        "-pix_fmt", VIDEO_PIXEL_FORMAT,
        "-crf", VIDEO_CRF,
        "-shortest",
        str(output_path),
    ]

    logger.info("Rendering video: %s + %s -> %s", image_path.name, audio_path.name, output_path.name)
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    if not output_path.exists():
        raise FileNotFoundError(f"ffmpeg did not produce output at {output_path}")

    return output_path


def render_short_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    start_time: float = 0.0,
    duration: float = SHORT_DURATION_SECONDS,
) -> Path:
    """Render a 9:16 YouTube Short video with 20% black bar top/bottom
    and trimmed landscape video in the middle 60% height.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_graph = (
        f"[0:v]scale=-1:{SHORT_CONTENT_HEIGHT},"
        f"crop={SHORT_VIDEO_WIDTH}:{SHORT_CONTENT_HEIGHT}:(iw-{SHORT_VIDEO_WIDTH})/2:0,"
        f"pad={SHORT_VIDEO_WIDTH}:{SHORT_VIDEO_HEIGHT}:0:{SHORT_BAR_HEIGHT}:black[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(video_path),
        "-ss", "0.0",
        "-t", f"{duration:.3f}",
        "-i", str(audio_path),
        "-filter_complex", filter_graph,
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", VIDEO_CODEC,
        "-preset", SHORT_PRESET,
        "-pix_fmt", VIDEO_PIXEL_FORMAT,
        "-crf", SHORT_VIDEO_CRF,
        "-c:a", AUDIO_CODEC,
        "-b:a", AUDIO_BITRATE,
        "-shortest",
        str(output_path),
    ]

    logger.info(
        "Rendering short video: %s (ss=%.2f) + %s -> %s (dur=%.2f)",
        video_path.name,
        start_time,
        audio_path.name,
        output_path.name,
        duration,
    )
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    if not output_path.exists():
        raise FileNotFoundError(f"ffmpeg did not produce short video output at {output_path}")

    return output_path


def render_short_preview_frame(
    video_path: Path,
    output_image_path: Path,
    start_time: float = 0.0,
) -> Path:
    """Render a single PNG preview frame of the 9:16 Short layout."""
    output_image_path.parent.mkdir(parents=True, exist_ok=True)

    filter_graph = (
        f"scale=-1:{SHORT_CONTENT_HEIGHT},"
        f"crop={SHORT_VIDEO_WIDTH}:{SHORT_CONTENT_HEIGHT}:(iw-{SHORT_VIDEO_WIDTH})/2:0,"
        f"pad={SHORT_VIDEO_WIDTH}:{SHORT_VIDEO_HEIGHT}:0:{SHORT_BAR_HEIGHT}:black"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_time:.3f}",
        "-i", str(video_path),
        "-vf", filter_graph,
        "-vframes", "1",
        str(output_image_path),
    ]

    logger.info("Rendering short preview frame: %s (ss=%.2f) -> %s", video_path.name, start_time, output_image_path.name)
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    if not output_image_path.exists():
        raise FileNotFoundError(f"ffmpeg did not produce preview frame at {output_image_path}")

    return output_image_path
