import logging
import subprocess
from pathlib import Path

from yt_song_to_instrumental.constants import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
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
