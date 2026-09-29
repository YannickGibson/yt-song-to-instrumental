import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from yt_song_to_instrumental.audio_alignment import align_short_audio
from yt_song_to_instrumental.constants import SHORT_ALIGNMENT_SAMPLE_RATE


def _music(seconds=70, seed=19):
    """Unique, changing harmonics plus transients; no copyrighted test media."""
    rng = np.random.default_rng(seed)
    rate = SHORT_ALIGNMENT_SAMPLE_RATE
    result = np.zeros(seconds * rate, dtype=np.float32)
    for first in range(0, len(result), rate // 4):
        count = min(rate // 4, len(result) - first)
        time = np.arange(count) / rate
        frequency = rng.uniform(150, 1400)
        result[first:first + count] = (
            np.sin(2 * np.pi * frequency * time)
            + 0.4 * np.sin(4 * np.pi * frequency * time)
            + 0.1 * rng.normal(size=count)
        ) * np.hanning(count) * rng.uniform(0.1, 0.5)
    return result


def _write(path: Path, samples):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar",
         str(SHORT_ALIGNMENT_SAMPLE_RATE), "-ac", "1", "-i", "pipe:0", str(path)],
        input=np.asarray(samples, dtype="<f4").tobytes(),
        capture_output=True, check=True,
    )
    return path


@pytest.fixture
def music():
    return _music()


def _align(tmp_path, release, video, start=10.0, trim=0.0, exact=True):
    return align_short_audio(
        _write(tmp_path / "release.wav", release),
        _write(tmp_path / "video.wav", video),
        audio_start_seconds=start,
        trim_start_seconds=trim,
        instrumental_duration=len(release) / SHORT_ALIGNMENT_SAMPLE_RATE - trim,
        exact_start=exact,
    )


def test_intro_gain_noise_and_lossy_encoding(tmp_path, music):
    rate = SHORT_ALIGNMENT_SAMPLE_RATE
    delay = 3.157
    rng = np.random.default_rng(35)
    video = np.concatenate([np.zeros(round(delay * rate)), music * 0.35])
    video += rng.normal(scale=0.001, size=len(video))
    result = align_short_audio(
        _write(tmp_path / "release audio.wav", music),
        _write(tmp_path / "video audio.m4a", video),
        audio_start_seconds=13.37,
        trim_start_seconds=2.5,
        instrumental_duration=67.5,
        exact_start=True,
    )
    assert result is not None
    assert result.video_start_seconds == pytest.approx(13.37 + 2.5 + delay, abs=0.025)
    assert result.audio_start_seconds == 13.37
    assert result.weakest_block_score > 0.65


@pytest.mark.parametrize("removed", [False, True])
def test_insertions_and_cuts_before_selected_passage(tmp_path, music, removed):
    rate = SHORT_ALIGNMENT_SAMPLE_RATE
    if removed:
        video = np.concatenate([music[:5 * rate], music[9 * rate:]])
        offset = -4
    else:
        video = np.concatenate([music[:5 * rate], np.zeros(4 * rate), music[5 * rate:]])
        offset = 4
    result = _align(tmp_path, music, video, start=20.0)
    assert result is not None
    assert result.video_start_seconds == pytest.approx(20 + offset, abs=0.025)


@pytest.mark.parametrize("edit", ["pause", "cut", "speed"])
def test_rejects_edits_or_drift_within_requested_segment(tmp_path, music, edit):
    rate = SHORT_ALIGNMENT_SAMPLE_RATE
    if edit == "pause":
        video = np.concatenate([music[:20 * rate], np.zeros(rate), music[20 * rate:]])
    elif edit == "cut":
        video = np.concatenate([music[:20 * rate], music[21 * rate:]])
    else:
        video = np.interp(np.arange(0, len(music), 1.02), np.arange(len(music)), music)
    assert _align(tmp_path, music, video) is None


def test_automatic_selection_finds_continuous_passage_after_pause(tmp_path, music):
    rate = SHORT_ALIGNMENT_SAMPLE_RATE
    video = np.concatenate([music[:15 * rate], np.zeros(3 * rate), music[15 * rate:]])
    result = _align(tmp_path, music, video, exact=False)
    assert result is not None
    assert result.audio_start_seconds >= 15
    assert result.video_start_seconds - result.audio_start_seconds == pytest.approx(3, abs=0.025)


@pytest.mark.parametrize("kind", ["different", "silence", "ambiguous"])
def test_rejects_unrelated_silent_and_ambiguous_soundtracks(tmp_path, music, kind):
    if kind == "different":
        video = _music(seed=72)
    elif kind == "silence":
        video = np.zeros_like(music)
    else:
        video = np.tile(music, 2)
    assert _align(tmp_path, music, video) is None


def test_same_source_preserves_timeline_and_trim_even_with_repeated_music(tmp_path, music):
    path = _write(tmp_path / "release.wav", np.tile(music, 2))
    result = align_short_audio(path, path, audio_start_seconds=13.37,
                               trim_start_seconds=2.5, instrumental_duration=137.5,
                               exact_start=True)
    assert result is not None
    assert result.video_start_seconds == pytest.approx(15.87)
    assert result.audio_start_seconds == 13.37


@pytest.mark.parametrize("start,duration", [(60.0, 70.0), (0.0, 19.0)])
def test_does_not_truncate_requested_clip(tmp_path, music, start, duration):
    path = _write(tmp_path / "release.wav", music)
    assert align_short_audio(path, path, audio_start_seconds=start, trim_start_seconds=0,
                             instrumental_duration=duration, exact_start=True) is None


def test_missing_audio_and_decode_timeout_fail_closed(tmp_path):
    path = tmp_path / "missing.wav"
    assert align_short_audio(path, path, audio_start_seconds=10, trim_start_seconds=0,
                             instrumental_duration=70) is None
    with patch("yt_song_to_instrumental.audio_alignment.subprocess.run",
               side_effect=subprocess.TimeoutExpired("ffmpeg", 90)):
        assert align_short_audio(path, path, audio_start_seconds=10, trim_start_seconds=0,
                                 instrumental_duration=70) is None
