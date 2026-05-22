from pathlib import Path
from unittest.mock import patch, call

from yt_song_to_instrumental.video_render import render_video
from yt_song_to_instrumental.constants import VIDEO_CODEC, AUDIO_CODEC, AUDIO_BITRATE, VIDEO_CRF, VIDEO_PIXEL_FORMAT


class TestRenderVideo:
    def test_calls_ffmpeg_with_correct_args(self, tmp_path):
        image = tmp_path / "thumb.jpg"
        audio = tmp_path / "instrumental.wav"
        output = tmp_path / "output.mp4"
        image.write_bytes(b"\xff\xd8")
        audio.write_bytes(b"\x00")

        def fake_run(cmd, **kwargs):
            output.write_bytes(b"\x00\x00\x00\x20ftypisom")
            return _mock_result()

        with patch("yt_song_to_instrumental.video_render.subprocess.run", side_effect=fake_run) as mock_run:
            result = render_video(image, audio, output)

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert str(image) in cmd
        assert str(audio) in cmd
        assert VIDEO_CODEC in cmd
        assert AUDIO_CODEC in cmd
        assert AUDIO_BITRATE in cmd

    def test_creates_parent_dir(self, tmp_path):
        image = tmp_path / "thumb.jpg"
        audio = tmp_path / "audio.wav"
        output = tmp_path / "nested" / "dir" / "output.mp4"
        image.write_bytes(b"\xff\xd8")
        audio.write_bytes(b"\x00")

        def fake_run(cmd, **kwargs):
            output.write_bytes(b"\x00")
            return _mock_result()

        with patch("yt_song_to_instrumental.video_render.subprocess.run", side_effect=fake_run):
            render_video(image, audio, output)

        assert output.parent.exists()


class _mock_result:
    def __init__(self):
        self.stdout = ""
        self.stderr = ""
        self.returncode = 0
