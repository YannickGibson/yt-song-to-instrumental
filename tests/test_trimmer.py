import numpy as np
import pytest
import soundfile as sf
from pathlib import Path
from unittest.mock import patch, MagicMock

from yt_song_to_instrumental.trimmer import detect_silence_threshold, trim_audio_file


def test_detect_silence_threshold(tmp_path):
    # Create a dummy audio file:
    # 1.0s of silence (0.0s)
    # 2.0s of sound (1.0s)
    # 1.0s of silence (0.0s)
    # Total 4.0s
    sr = 16000
    silence_start = np.zeros(sr)
    sound = np.ones(sr * 2) * 0.1  # ~ -20dB RMS
    silence_end = np.zeros(sr)
    
    y = np.concatenate([silence_start, sound, silence_end])
    audio_path = tmp_path / "test_silence.wav"
    sf.write(str(audio_path), y, sr)

    # With -35dB threshold, it should detect start trim around 1.0s and end trim around 3.0s
    start_t, end_t, dur = detect_silence_threshold(audio_path, threshold_db=-35.0)
    
    assert abs(dur - 4.0) < 0.05
    # The start trim should be close to 1.0s (first non-silent window)
    assert abs(start_t - 1.0) < 0.1
    # The end trim should be close to 3.0s (last non-silent window)
    assert abs(end_t - 3.0) < 0.1


def test_detect_silence_threshold_no_trim_if_all_loud(tmp_path):
    sr = 16000
    y = np.ones(sr * 3) * 0.1  # all loud
    audio_path = tmp_path / "test_loud.wav"
    sf.write(str(audio_path), y, sr)

    start_t, end_t, dur = detect_silence_threshold(audio_path, threshold_db=-35.0)
    
    assert start_t == 0.0
    assert end_t == dur
    assert abs(dur - 3.0) < 0.05


def test_detect_silence_threshold_no_trim_if_all_silent(tmp_path):
    sr = 16000
    y = np.zeros(sr * 3)  # all silent
    audio_path = tmp_path / "test_silent.wav"
    sf.write(str(audio_path), y, sr)

    start_t, end_t, dur = detect_silence_threshold(audio_path, threshold_db=-35.0)
    
    assert start_t == 0.0
    assert end_t == dur
    assert abs(dur - 3.0) < 0.05


@patch("yt_song_to_instrumental.trimmer.subprocess.run")
def test_trim_audio_file(mock_run):
    input_p = Path("/path/to/in.wav")
    output_p = Path("/path/to/out.wav")
    
    trim_audio_file(input_p, output_p, start_time=1.234, end_time=5.678)
    
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "ffmpeg"
    assert "-ss" in args
    assert "1.234" in args
    assert "-to" in args
    assert "5.678" in args
