"""Locate a continuous release-audio passage in a music-video soundtrack.

FFmpeg decodes both original mixes to the same PCM format. Spectral changes
provide a gain/EQ-tolerant fingerprint; local checks reject edits and drift
inside the clip. No separated vocals or model inference is needed here.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from yt_song_to_instrumental.constants import (
    SHORT_ALIGNMENT_BANDS,
    SHORT_ALIGNMENT_BLOCK_SECONDS,
    SHORT_ALIGNMENT_CANDIDATE_STEP_SECONDS,
    SHORT_ALIGNMENT_DECODE_COMMAND,
    SHORT_ALIGNMENT_DECODE_ERROR,
    SHORT_ALIGNMENT_DECODE_OPTIONS,
    SHORT_ALIGNMENT_EPSILON,
    SHORT_ALIGNMENT_HIGH_HZ,
    SHORT_ALIGNMENT_HOP_SAMPLES,
    SHORT_ALIGNMENT_INPUT_ERROR,
    SHORT_ALIGNMENT_LOCAL_SEARCH_SECONDS,
    SHORT_ALIGNMENT_LOW_HZ,
    SHORT_ALIGNMENT_MATCH_LOG,
    SHORT_ALIGNMENT_MAX_CANDIDATES,
    SHORT_ALIGNMENT_MAX_DRIFT_SECONDS,
    SHORT_ALIGNMENT_MAX_SECONDS,
    SHORT_ALIGNMENT_MIN_BLOCK_SCORE,
    SHORT_ALIGNMENT_MIN_MARGIN,
    SHORT_ALIGNMENT_MIN_RMS,
    SHORT_ALIGNMENT_MIN_SCORE,
    SHORT_ALIGNMENT_NO_MATCH,
    SHORT_ALIGNMENT_PCM_DTYPE,
    SHORT_ALIGNMENT_PEAK_EXCLUSION_SECONDS,
    SHORT_ALIGNMENT_SAMPLE_RATE,
    SHORT_ALIGNMENT_SMOOTH_FRAMES,
    SHORT_ALIGNMENT_SMOOTH_MODE,
    SHORT_ALIGNMENT_TIMEOUT_SECONDS,
    SHORT_ALIGNMENT_WINDOW_SAMPLES,
    SHORT_DEFAULT_START_SECONDS,
    SHORT_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)
_FRAME_SECONDS = SHORT_ALIGNMENT_HOP_SAMPLES / SHORT_ALIGNMENT_SAMPLE_RATE


@dataclass(frozen=True)
class ShortAlignment:
    video_start_seconds: float
    audio_start_seconds: float
    score: float
    weakest_block_score: float
    margin: float


def _decode_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        [*SHORT_ALIGNMENT_DECODE_COMMAND, str(path), *SHORT_ALIGNMENT_DECODE_OPTIONS],
        capture_output=True, check=True, timeout=SHORT_ALIGNMENT_TIMEOUT_SECONDS,
    )
    samples = np.frombuffer(result.stdout, dtype=SHORT_ALIGNMENT_PCM_DTYPE)
    if (len(samples) < SHORT_ALIGNMENT_WINDOW_SAMPLES
            or len(samples) > SHORT_ALIGNMENT_MAX_SECONDS * SHORT_ALIGNMENT_SAMPLE_RATE
            or not np.isfinite(samples).all()
            or np.sqrt(np.mean(np.square(samples))) < SHORT_ALIGNMENT_MIN_RMS):
        raise ValueError(SHORT_ALIGNMENT_INPUT_ERROR)
    return samples


def _fingerprint(samples: np.ndarray) -> np.ndarray:
    windows = np.lib.stride_tricks.sliding_window_view(
        samples, SHORT_ALIGNMENT_WINDOW_SAMPLES,
    )[::SHORT_ALIGNMENT_HOP_SAMPLES]
    power = np.abs(np.fft.rfft(
        windows * np.hanning(SHORT_ALIGNMENT_WINDOW_SAMPLES), axis=1,
    )) ** 2
    frequencies = np.fft.rfftfreq(
        SHORT_ALIGNMENT_WINDOW_SAMPLES, 1 / SHORT_ALIGNMENT_SAMPLE_RATE,
    )
    edges = np.geomspace(
        SHORT_ALIGNMENT_LOW_HZ, SHORT_ALIGNMENT_HIGH_HZ, SHORT_ALIGNMENT_BANDS + 1,
    )
    bands = np.stack([
        np.log(np.maximum(
            power[:, (frequencies >= low) & (frequencies < high)].mean(axis=1),
            SHORT_ALIGNMENT_EPSILON,
        )) for low, high in zip(edges[:-1], edges[1:])
    ], axis=1)
    # Remove static mastering differences without normalizing silent frames
    # into spurious matches. The same filter is applied to complete recordings.
    smooth_frames = min(SHORT_ALIGNMENT_SMOOTH_FRAMES, len(bands))
    smooth = np.ones(smooth_frames) / smooth_frames
    bands -= np.stack([
        np.convolve(band, smooth, mode=SHORT_ALIGNMENT_SMOOTH_MODE) for band in bands.T
    ], axis=1)
    bands /= np.maximum(
        np.linalg.norm(bands, axis=1, keepdims=True), SHORT_ALIGNMENT_EPSILON,
    )
    rms = np.sqrt(np.mean(windows ** 2, axis=1))
    bands[rms < SHORT_ALIGNMENT_MIN_RMS] = SHORT_DEFAULT_START_SECONDS
    return bands.astype(np.float32)


def _match_scores(search: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Cosine similarity at every valid time lag, using bounded FFT correlation."""
    fft_size = 1 << (len(search) + len(query) - 1).bit_length()
    cross = np.fft.rfft(search, n=fft_size, axis=0) * np.conj(
        np.fft.rfft(query, n=fft_size, axis=0),
    )
    return np.fft.irfft(cross.sum(axis=1), n=fft_size)[:len(search) - len(query) + 1] / len(query)


def _verify_continuity(search: np.ndarray, query: np.ndarray, start: int) -> float | None:
    block_size = round(SHORT_ALIGNMENT_BLOCK_SECONDS / _FRAME_SECONDS)
    radius = round(SHORT_ALIGNMENT_LOCAL_SEARCH_SECONDS / _FRAME_SECONDS)
    weakest = float(np.inf)
    offsets = np.linspace(0, len(query), max(1, len(query) // block_size) + 1, dtype=int)
    for offset, end in zip(offsets[:-1], offsets[1:]):
        block = query[offset:end]
        expected = start + offset
        low = max(0, expected - radius)
        high = min(len(search), expected + len(block) + radius)
        scores = _match_scores(search[low:high], block)
        actual = low + int(np.argmax(scores))
        score = float(scores[expected - low])
        if (score < SHORT_ALIGNMENT_MIN_BLOCK_SCORE
                or abs(actual - expected) * _FRAME_SECONDS > SHORT_ALIGNMENT_MAX_DRIFT_SECONDS):
            return None
        weakest = min(weakest, score)
    return weakest


def align_short_audio(
    release_audio: Path,
    video_audio: Path,
    *,
    audio_start_seconds: float,
    trim_start_seconds: float,
    instrumental_duration: float,
    exact_start: bool = False,
    duration: float = SHORT_DURATION_SECONDS,
) -> ShortAlignment | None:
    """Match an instrumental content offset to the original video soundtrack.

    An explicit request keeps its exact content offset. Automatic selection may
    try nearby passages if a video edit crosses the preferred passage. Every
    accepted result contains a full, continuously aligned clip in both files.
    Failures remain retryable; the caller must never fall back to equal offsets.
    """
    values = (audio_start_seconds, trim_start_seconds, instrumental_duration, duration)
    if (not all(np.isfinite(value) for value in values)
            or min(values) < SHORT_DEFAULT_START_SECONDS
            or duration <= SHORT_DEFAULT_START_SECONDS):
        return None
    try:
        release = _decode_audio(release_audio)
        video = release if release_audio == video_audio else _decode_audio(video_audio)
    except (OSError, ValueError, subprocess.SubprocessError):
        logger.warning(SHORT_ALIGNMENT_DECODE_ERROR, exc_info=True)
        return None
    available = min(instrumental_duration,
                    len(release) / SHORT_ALIGNMENT_SAMPLE_RATE - trim_start_seconds)
    max_start = available - duration
    if max_start < SHORT_DEFAULT_START_SECONDS or len(video) / SHORT_ALIGNMENT_SAMPLE_RATE < duration:
        return None
    if exact_start and audio_start_seconds > max_start:
        return None
    preferred = min(audio_start_seconds, max_start)
    candidates = [preferred]
    if not exact_start:
        candidates.extend(sorted(
            (float(start) for start in np.arange(
                SHORT_DEFAULT_START_SECONDS, max_start, SHORT_ALIGNMENT_CANDIDATE_STEP_SECONDS,
            ) if start != preferred), key=lambda start: abs(start - preferred),
        ))
    reference = _fingerprint(release)
    search = reference if release_audio == video_audio else _fingerprint(video)
    # Fingerprint windows must remain wholly within the rendered clip.
    count = int((duration * SHORT_ALIGNMENT_SAMPLE_RATE - SHORT_ALIGNMENT_WINDOW_SAMPLES)
                // SHORT_ALIGNMENT_HOP_SAMPLES) + 1
    if count < round(SHORT_ALIGNMENT_BLOCK_SECONDS / _FRAME_SECONDS):
        return None
    for audio_start in candidates[:SHORT_ALIGNMENT_MAX_CANDIDATES]:
        release_start = audio_start + trim_start_seconds
        first = int(release_start / _FRAME_SECONDS)
        query = reference[first:first + count]
        if len(query) != count or len(search) < count:
            continue
        # Matching fingerprints alone must not permit a partial final frame.
        max_video_start = len(video) / SHORT_ALIGNMENT_SAMPLE_RATE - duration
        if release_audio == video_audio:
            # Same source ID has a known timeline, even for repeated choruses.
            best = first
            score = float(np.sum(query * query) / count)
            margin = score
        else:
            scores = _match_scores(search, query)
            scores = scores[:int(max_video_start / _FRAME_SECONDS) + 1]
            best = int(np.argmax(scores))
            score = float(scores[best])
            exclusion = round(SHORT_ALIGNMENT_PEAK_EXCLUSION_SECONDS / _FRAME_SECONDS)
            rivals = scores.copy()
            rivals[max(0, best - exclusion):best + exclusion + 1] = -np.inf
            runner_up = float(np.max(rivals))
            margin = score - runner_up if np.isfinite(runner_up) else score
        if score < SHORT_ALIGNMENT_MIN_SCORE or margin < SHORT_ALIGNMENT_MIN_MARGIN:
            continue
        weakest = _verify_continuity(search, query, best)
        if weakest is None:
            continue
        # Retain the exact user offset; transfer the sub-frame remainder to video.
        video_start = best * _FRAME_SECONDS + release_start - first * _FRAME_SECONDS
        if video_start < SHORT_DEFAULT_START_SECONDS or video_start > max_video_start:
            continue
        result = ShortAlignment(video_start, audio_start, score, weakest, margin)
        logger.info(SHORT_ALIGNMENT_MATCH_LOG, video_start, release_start,
                    audio_start, score, weakest, margin)
        return result
    logger.warning(SHORT_ALIGNMENT_NO_MATCH)
    return None
