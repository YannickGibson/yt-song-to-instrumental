import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from yt_song_to_instrumental.constants import (
    MAX_SILENCE_RATIO,
    MIN_DURATION_SECONDS,
    SILENCE_THRESHOLD_DB,
)

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    passed: bool
    duration_seconds: float
    silence_ratio: float
    reasons: list[str] = field(default_factory=list)


def check_quality(audio_path: Path) -> QualityResult:
    reasons: list[str] = []

    if not audio_path.exists() or audio_path.stat().st_size == 0:
        return QualityResult(passed=False, duration_seconds=0.0, silence_ratio=1.0, reasons=["File missing or empty"])

    duration = _get_duration(audio_path)
    if duration < MIN_DURATION_SECONDS:
        reasons.append(f"Duration {duration:.1f}s below minimum {MIN_DURATION_SECONDS}s")

    silence_ratio = _get_silence_ratio(audio_path, duration)
    if silence_ratio > MAX_SILENCE_RATIO:
        reasons.append(f"Silence ratio {silence_ratio:.2f} exceeds maximum {MAX_SILENCE_RATIO}")

    passed = len(reasons) == 0
    return QualityResult(passed=passed, duration_seconds=duration, silence_ratio=silence_ratio, reasons=reasons)


def _get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _get_silence_ratio(path: Path, total_duration: float) -> float:
    if total_duration <= 0:
        return 1.0

    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af",
         f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d=0.5",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )

    stderr = result.stderr
    silence_duration = 0.0
    for line in stderr.split("\n"):
        if "silence_duration:" in line:
            parts = line.split("silence_duration:")
            if len(parts) > 1:
                try:
                    silence_duration += float(parts[1].strip())
                except ValueError:
                    pass

    return min(silence_duration / total_duration, 1.0)
