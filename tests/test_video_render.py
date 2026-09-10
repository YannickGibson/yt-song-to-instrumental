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


class TestRenderShortVideo:
    def test_calls_ffmpeg_with_short_filter_complex(self, tmp_path):
        from yt_song_to_instrumental.video_render import render_short_video

        video = tmp_path / "source.mp4"
        audio = tmp_path / "instrumental.wav"
        output = tmp_path / "short.mp4"
        video.write_bytes(b"\x00")
        audio.write_bytes(b"\x00")

        def fake_run(cmd, **kwargs):
            output.write_bytes(b"\x00\x00\x00\x20ftypisom")
            return _mock_result()

        with patch("yt_song_to_instrumental.video_render.subprocess.run", side_effect=fake_run) as mock_run:
            result = render_short_video(
                video,
                audio,
                output,
                start_time=38.5,
                audio_start_time=35.0,
                duration=20.0,
            )

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert str(video) in cmd
        assert str(audio) in cmd
        assert "38.500" in cmd
        assert "35.000" in cmd
        assert "20.000" in cmd
        assert "-filter_complex" in cmd
        filter_str = cmd[cmd.index("-filter_complex") + 1]
        assert "scale=-1:1152" in filter_str
        assert "crop=1080:1152" in filter_str
        assert "pad=1080:1920:0:384:black" in filter_str


class TestRenderShortPreviewFrame:
    def test_calls_ffmpeg_preview_frame(self, tmp_path):
        from yt_song_to_instrumental.video_render import render_short_preview_frame

        video = tmp_path / "source.mp4"
        output = tmp_path / "preview.png"
        video.write_bytes(b"\x00")

        def fake_run(cmd, **kwargs):
            output.write_bytes(b"\x89PNG")
            return _mock_result()

        with patch("yt_song_to_instrumental.video_render.subprocess.run", side_effect=fake_run) as mock_run:
            result = render_short_preview_frame(video, output, start_time=3.5)

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert str(video) in cmd
        assert "3.500" in cmd
        assert "-vframes" in cmd


class _mock_result:
    def __init__(self):
        self.stdout = ""
        self.stderr = ""
        self.returncode = 0
