"""Sequence-level regressions: scene variety alone must not approve loops."""
from pathlib import Path
import subprocess
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from yt_song_to_instrumental.constants import (
    SHORT_STRUCTURE_FPS, SHORT_STRUCTURE_WIDTH, SHORT_STRUCTURE_HEIGHT,
    SHORT_STRUCTURE_MAX_SECONDS,
)
from yt_song_to_instrumental.video_detector import (
    _loop_evidence, _sample_source, detect_if_music_video,
)


def _scenes(count, seed=17):
    rng = np.random.default_rng(seed)
    return np.stack([np.asarray(Image.fromarray(rng.integers(
        20, 230, (6, 8), dtype=np.uint8)).resize(
            (SHORT_STRUCTURE_WIDTH, SHORT_STRUCTURE_HEIGHT))) for _ in range(count)])


@pytest.mark.parametrize("seconds", [4, 27, 40, 80])
def test_multiscene_sequence_repetition(seconds):
    cycle = _scenes(int(seconds * SHORT_STRUCTURE_FPS))
    frames = np.concatenate([cycle, cycle, cycle])
    repeated, period, coverage = _loop_evidence(frames)
    assert repeated
    assert abs(period - seconds) <= 1 / SHORT_STRUCTURE_FPS
    assert coverage > .9


def test_loop_survives_intro_outro_and_brightness_change():
    cycle = _scenes(160)
    altered = np.clip(cycle.astype(float) * .85 + 15, 0, 255).astype(np.uint8)
    frames = np.concatenate([_scenes(16, 1), cycle, altered, cycle, _scenes(16, 2)])
    repeated, period, _ = _loop_evidence(frames)
    assert repeated
    assert abs(period - 40) <= 1 / SHORT_STRUCTURE_FPS


def test_many_unrelated_scenes_are_not_a_loop():
    assert not _loop_evidence(_scenes(400))[0]


def test_repeated_brief_shot_is_not_a_whole_video_loop():
    frames = _scenes(400)
    frames[160:180] = frames[40:60]
    frames[300:320] = frames[40:60]
    assert not _loop_evidence(frames)[0]


def test_matches_must_be_spread_over_the_sequence():
    frames = _scenes(400)
    frames[160:260] = frames[:100]
    assert not _loop_evidence(frames)[0]


def test_static_and_flash_frames_do_not_fake_a_periodic_peak():
    # These are rejected by motion/diversity, not reported as confident loops.
    frames = np.zeros((80, SHORT_STRUCTURE_HEIGHT, SHORT_STRUCTURE_WIDTH), dtype=np.uint8)
    frames[::2] = 255
    assert not _loop_evidence(frames)[0]


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("ffmpeg", 1), OSError("missing")])
def test_decode_failure_is_closed(failure):
    with patch("yt_song_to_instrumental.video_detector.subprocess.run", side_effect=failure):
        assert _sample_source(Path("source.mp4"), 60) is None


def test_duration_limit_does_not_analyze_just_the_beginning():
    with patch("yt_song_to_instrumental.video_detector.subprocess.run") as run:
        assert _sample_source(Path("source.mp4"), SHORT_STRUCTURE_MAX_SECONDS + 1) is None
        run.assert_not_called()


def test_truncated_decode_is_rejected():
    with patch("yt_song_to_instrumental.video_detector.subprocess.run") as run:
        run.return_value.stdout = bytes(SHORT_STRUCTURE_WIDTH * SHORT_STRUCTURE_HEIGHT * 10)
        assert _sample_source(Path("source.mp4"), 60) is None


def test_pipeline_entrypoint_rejects_loop_even_with_positive_title(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    cycle = _scenes(160)
    with patch("yt_song_to_instrumental.video_detector._probe_duration", return_value=120), \
         patch("yt_song_to_instrumental.video_detector._sample_source", return_value=np.tile(cycle, (3, 1, 1))):
        eligible, motion = detect_if_music_video(source, video_title="Artist - Track (Official Music Video)")
    assert motion > 10
    assert eligible is False


def test_pipeline_entrypoint_accepts_nonlooping_scenes(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    with patch("yt_song_to_instrumental.video_detector._probe_duration", return_value=100), \
         patch("yt_song_to_instrumental.video_detector._sample_source", return_value=_scenes(400)):
        eligible, _ = detect_if_music_video(source, video_title="Artist - Track (Official Music Video)")
    assert eligible is True


@pytest.mark.parametrize("title", ["Track (Concert)", "Track [Visualiser]", "Track - Trailer"])
def test_excluded_source_formats(title, tmp_path):
    with patch("yt_song_to_instrumental.video_detector._sample_source") as sample:
        assert detect_if_music_video(tmp_path / "source.mp4", video_title=title) == (False, 0.0)
        sample.assert_not_called()
