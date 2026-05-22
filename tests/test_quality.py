import json
from pathlib import Path
from unittest.mock import patch

from yt_song_to_instrumental.quality import QualityResult, check_quality, _get_duration, _get_silence_ratio


class TestCheckQuality:
    def test_missing_file_fails(self, tmp_path):
        result = check_quality(tmp_path / "nonexistent.wav")
        assert result.passed is False
        assert "missing or empty" in result.reasons[0].lower()

    def test_empty_file_fails(self, tmp_path):
        f = tmp_path / "empty.wav"
        f.touch()
        result = check_quality(f)
        assert result.passed is False

    def test_passing_quality(self, tmp_path):
        f = tmp_path / "good.wav"
        f.write_bytes(b"\x00" * 1024)

        ffprobe_output = json.dumps({"format": {"duration": "180.0"}})
        ffmpeg_stderr = "silence_duration: 10.0\n"

        with patch("yt_song_to_instrumental.quality.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout=ffprobe_output),
                _mock_result(stderr=ffmpeg_stderr),
            ]
            result = check_quality(f)

        assert result.passed is True
        assert result.duration_seconds == 180.0
        assert result.silence_ratio < 0.5

    def test_short_duration_fails(self, tmp_path):
        f = tmp_path / "short.wav"
        f.write_bytes(b"\x00" * 1024)

        ffprobe_output = json.dumps({"format": {"duration": "10.0"}})
        ffmpeg_stderr = ""

        with patch("yt_song_to_instrumental.quality.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout=ffprobe_output),
                _mock_result(stderr=ffmpeg_stderr),
            ]
            result = check_quality(f)

        assert result.passed is False
        assert any("duration" in r.lower() for r in result.reasons)

    def test_too_much_silence_fails(self, tmp_path):
        f = tmp_path / "silent.wav"
        f.write_bytes(b"\x00" * 1024)

        ffprobe_output = json.dumps({"format": {"duration": "60.0"}})
        ffmpeg_stderr = "silence_duration: 40.0\n"

        with patch("yt_song_to_instrumental.quality.subprocess.run") as mock_run:
            mock_run.side_effect = [
                _mock_result(stdout=ffprobe_output),
                _mock_result(stderr=ffmpeg_stderr),
            ]
            result = check_quality(f)

        assert result.passed is False
        assert any("silence" in r.lower() for r in result.reasons)


class TestGetDuration:
    def test_parses_ffprobe_output(self):
        ffprobe_output = json.dumps({"format": {"duration": "245.5"}})
        with patch("yt_song_to_instrumental.quality.subprocess.run") as mock_run:
            mock_run.return_value = _mock_result(stdout=ffprobe_output)
            duration = _get_duration(Path("/fake/file.wav"))
        assert duration == 245.5


class TestGetSilenceRatio:
    def test_parses_silence_detect_output(self):
        stderr = (
            "[silencedetect] silence_start: 0.0\n"
            "[silencedetect] silence_end: 5.0 | silence_duration: 5.0\n"
            "[silencedetect] silence_start: 50.0\n"
            "[silencedetect] silence_end: 60.0 | silence_duration: 10.0\n"
        )
        with patch("yt_song_to_instrumental.quality.subprocess.run") as mock_run:
            mock_run.return_value = _mock_result(stderr=stderr)
            ratio = _get_silence_ratio(Path("/fake/file.wav"), 100.0)
        assert ratio == 0.15

    def test_zero_duration_returns_one(self):
        ratio = _get_silence_ratio(Path("/fake/file.wav"), 0.0)
        assert ratio == 1.0

    def test_no_silence_returns_zero(self):
        with patch("yt_song_to_instrumental.quality.subprocess.run") as mock_run:
            mock_run.return_value = _mock_result(stderr="")
            ratio = _get_silence_ratio(Path("/fake/file.wav"), 60.0)
        assert ratio == 0.0


class _mock_result:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
