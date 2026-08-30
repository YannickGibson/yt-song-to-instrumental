import logging
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf

from yt_song_to_instrumental.constants import (
    DEFAULT_TRIM_MIN_DURATION_SECONDS,
    DEFAULT_TRIM_MIN_SUSTAINED_SECONDS,
)

logger = logging.getLogger(__name__)


def detect_silence_threshold(
    audio_path: Path,
    threshold_db: float,
    window_duration: float = 0.05,
    min_sustained_duration: float = DEFAULT_TRIM_MIN_SUSTAINED_SECONDS,
) -> tuple[float, float, float]:
    """Detects the start and end of non-silent sections based on decibel threshold.
    
    Requires non-silent sound to be sustained for at least `min_sustained_duration`
    (e.g., 0.3s) to ignore single transient spikes or clicks at the start/end.
    
    Returns:
        tuple[float, float, float]: (start_time, end_time, total_duration)
    """
    try:
        y, sr = sf.read(str(audio_path))
    except Exception as e:
        logger.error("Failed to read audio file %s for silence detection: %s", audio_path, e)
        raise

    total_duration = len(y) / sr
    if len(y.shape) > 1:
        y = np.mean(y, axis=1)

    window_len = int(window_duration * sr)
    step = window_len

    db_list = []
    times = []
    for i in range(0, len(y) - window_len + 1, step):
        chunk = y[i : i + window_len]
        rms = max(np.sqrt(np.mean(chunk**2)), 1e-10)
        db = 20 * np.log10(rms)
        db_list.append(db)
        times.append(i / sr)

    if not db_list:
        return 0.0, total_duration, total_duration

    required_consecutive = max(1, int(min_sustained_duration / window_duration))

    # Detect start_trim: first index where `required_consecutive` consecutive windows are >= threshold_db
    start_trim = 0.0
    consecutive = 0
    for idx, (t, db) in enumerate(zip(times, db_list)):
        if db >= threshold_db:
            consecutive += 1
            if consecutive >= required_consecutive:
                start_trim = times[idx - required_consecutive + 1]
                break
        else:
            consecutive = 0

    # Detect end_trim: last index where `required_consecutive` consecutive windows are >= threshold_db
    end_trim = total_duration
    consecutive = 0
    for idx in range(len(db_list) - 1, -1, -1):
        db = db_list[idx]
        if db >= threshold_db:
            consecutive += 1
            if consecutive >= required_consecutive:
                end_trim = times[idx + required_consecutive - 1] + window_duration
                break
        else:
            consecutive = 0

    # Sanity check: make sure start_trim < end_trim and the trimmed portion is not too short.
    if start_trim >= end_trim or (end_trim - start_trim) < DEFAULT_TRIM_MIN_DURATION_SECONDS:
        return 0.0, total_duration, total_duration

    return start_trim, end_trim, total_duration


def trim_audio_file(
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
) -> None:
    """Trims the audio file using ffmpeg via subprocess.
    
    All audio processing uses ffmpeg via subprocess — ensure paths are quoted/escaped.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ss", f"{start_time:.3f}",
        "-to", f"{end_time:.3f}",
        str(output_path),
    ]
    logger.info("Trimming audio: %s -> %s (ss: %.3f, to: %.3f)", input_path.name, output_path.name, start_time, end_time)
    subprocess.run(cmd, capture_output=True, text=True, check=True)
