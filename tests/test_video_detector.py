import tempfile
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PIL import Image, ImageDraw
import numpy as np

from yt_song_to_instrumental.video_detector import detect_if_music_video, get_source_video_title, _frame_correlation


def _create_synthetic_video(output_path: Path, is_static: bool, duration: float = 4.0, fps: int = 10):
    with tempfile.TemporaryDirectory() as frame_dir_str:
        frame_dir = Path(frame_dir_str)
        num_frames = int(duration * fps)
        for i in range(num_frames):
            if is_static:
                img = Image.new("RGB", (160, 90), color=(50, 50, 50))
                draw = ImageDraw.Draw(img)
                draw.ellipse([70, 35, 90, 55], fill=(200, 200, 200))
            else:
                rng = np.random.default_rng(i // 10)
                pixels = rng.integers(0, 256, (3, 4, 3), dtype=np.uint8)
                img = Image.fromarray(pixels).resize((160, 90), Image.Resampling.NEAREST)
            img.save(frame_dir / f"frame_{i:04d}.png")

        cmd = [
            "ffmpeg", "-y",
            "-r", str(fps),
            "-i", str(frame_dir / "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True)


def _create_fixed_layout_visualizer(output_path: Path, duration: float = 8.0, fps: int = 10):
    with tempfile.TemporaryDirectory() as frame_dir_str:
        frame_dir = Path(frame_dir_str)
        num_frames = int(duration * fps)
        for i in range(num_frames):
            pulse = 24 if (i // 5) % 2 == 0 else 0
            img = Image.new("RGB", (160, 90), color=(60 + pulse, 20 + pulse, 20 + pulse))
            draw = ImageDraw.Draw(img)
            draw.rectangle([45, 10, 115, 80], outline=(230, 230, 230), width=3)
            draw.polygon([(80, 20), (105, 65), (55, 65)], fill=(180, 80, 45))
            img.save(frame_dir / f"frame_{i:04d}.png")

        cmd = [
            "ffmpeg", "-y",
            "-r", str(fps),
            "-i", str(frame_dir / "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True)


def test_detect_static_video(tmp_path):
    video_path = tmp_path / "static.mp4"
    _create_synthetic_video(video_path, is_static=True, duration=6.0)
    
    is_music_vid, diff = detect_if_music_video(video_path, start_time=0.0, duration=6.0, min_motion_threshold=5.0, sample_fps=1.0)
    assert is_music_vid is False
    assert diff < 2.0


def test_detect_moving_video(tmp_path):
    video_path = tmp_path / "moving.mp4"
    _create_synthetic_video(video_path, is_static=False, duration=6.0)
    
    is_music_vid, diff = detect_if_music_video(video_path, start_time=0.0, duration=6.0, min_motion_threshold=5.0, sample_fps=1.0)
    assert is_music_vid is True
    assert diff > 5.0


def test_detect_fixed_layout_visualizer_with_motion(tmp_path):
    video_path = tmp_path / "visualizer.mp4"
    _create_fixed_layout_visualizer(video_path)

    is_music_vid, diff = detect_if_music_video(
        video_path,
        start_time=0.0,
        duration=8.0,
        min_motion_threshold=5.0,
        sample_fps=2.0,
    )

    assert diff > 5.0
    assert is_music_vid is False


def test_nonexistent_video(tmp_path):
    is_music_vid, diff = detect_if_music_video(tmp_path / "nonexistent.mp4")
    assert is_music_vid is False
    assert diff == 0.0


def test_audio_indicator_in_title_skips(tmp_path):
    video_path = tmp_path / "moving.mp4"
    _create_synthetic_video(video_path, is_static=False, duration=6.0)

    for title in (
        "Artist - Song (Official Audio)",
        "Artist - Song [Visualizer]",
        "Artist - Song (Lyric Video)",
        "Song (Audio)",
    ):
        is_mv, diff = detect_if_music_video(video_path, video_title=title)
        assert is_mv is False
        assert diff == 0.0


def test_uniform_flashes_are_not_scene_changes():
    assert _frame_correlation(np.zeros((10, 10)), np.full((10, 10), 255)) == 1.0


def test_raw_source_title_retains_visualizer_indicator():
    service = MagicMock()
    service.videos.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "source", "snippet": {"title": "Artist - Track (Official Visualizer)"}}]}
    assert get_source_video_title(service, "source") == "Artist - Track (Official Visualizer)"
    assert get_source_video_title(service, "other") is None


def test_raw_source_title_fails_closed():
    service = MagicMock()
    service.videos.return_value.list.return_value.execute.side_effect = RuntimeError()
    assert get_source_video_title(service, "source") is None
