from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.video_finder import (
    find_and_verify_music_video,
    search_channel_candidates,
    search_music_video_candidates,
)


class TestSearchChannelCandidates:
    @patch("yt_song_to_instrumental.video_finder.get_channel_videos")
    def test_finds_official_music_video_on_channel(self, mock_get_channel):
        mock_get_channel.return_value = [
            {"id": "v1", "title": "Sample Artist 9 - Tell Em (Audio)", "duration": 181},
            {"id": "v2", "title": "Sample Artist 9 - SANJI (Official Video)", "duration": 148},
            {"id": "v3", "title": "Sample Artist 9 - POCKET ROCKET (Official Video)", "duration": 133},
        ]

        candidates = search_channel_candidates(
            "https://youtube.com/@sample-artist", "SANJI", expected_duration=150.0
        )

        assert len(candidates) == 1
        assert candidates[0]["id"] == "v2"
        assert candidates[0]["priority"] == 1 or candidates[0]["priority"] == 2


class TestSearchMusicVideoCandidates:
    @patch("yt_dlp.YoutubeDL")
    def test_filters_negative_keywords(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "v1", "title": "Artist - Song (Reaction!)", "duration": 180, "uploader": "Reactor"},
                {"id": "v2", "title": "Artist - Song (Type Beat)", "duration": 180, "uploader": "Producer"},
                {"id": "v3", "title": "Artist - Song (Guitar Cover)", "duration": 180, "uploader": "Guitarist"},
                {"id": "v4", "title": "Artist - Song (Official Audio)", "duration": 180, "uploader": "Artist"},
                {"id": "v5", "title": "Artist - Song [Visualizer]", "duration": 180, "uploader": "Artist"},
                {"id": "v6", "title": "Artist - Song [Official Video]", "duration": 180, "uploader": "Artist"},
            ]
        }

        candidates = search_music_video_candidates("Artist", "Song", expected_duration=180.0)

        assert len(candidates) == 1
        assert candidates[0]["id"] == "v6"

    @patch("yt_dlp.YoutubeDL")
    def test_filters_duration_mismatch(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "v1", "title": "Artist - Song (Snippet)", "duration": 15, "uploader": "Fan"},
                {"id": "v2", "title": "Artist - Song (10 min loop)", "duration": 600, "uploader": "Looper"},
                {"id": "v3", "title": "Artist - Song [Music Video]", "duration": 175, "uploader": "Artist"},
            ]
        }

        candidates = search_music_video_candidates("Artist", "Song", expected_duration=170.0)

        assert len(candidates) == 1
        assert candidates[0]["id"] == "v3"

    @patch("yt_dlp.YoutubeDL")
    def test_requires_title_token_match(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "entries": [
                {"id": "v1", "title": "Totally Different Track - Official Video", "duration": 180, "uploader": "Artist"},
                {"id": "v2", "title": "Artist - Real Song [Official Video]", "duration": 180, "uploader": "Artist"},
            ]
        }

        candidates = search_music_video_candidates("Artist", "Real Song", expected_duration=180.0)

        assert len(candidates) == 1
        assert candidates[0]["id"] == "v2"


class TestFindAndVerifyMusicVideo:
    @patch("yt_song_to_instrumental.video_finder.detect_if_music_video")
    @patch("yt_song_to_instrumental.video_finder.download_source_video")
    @patch("yt_song_to_instrumental.video_finder.search_channel_candidates")
    def test_successful_channel_verification(self, mock_channel_search, mock_download, mock_detect, tmp_path):
        mock_channel_search.return_value = [{"id": "mv123", "title": "Sample Artist 9 - SANJI (Official Video)"}]
        mock_file = tmp_path / "video_mv123.mp4"
        mock_file.touch()
        mock_download.return_value = mock_file
        mock_detect.return_value = (True, 15.4)

        result_path, diff = find_and_verify_music_video(
            "Sample Artist 9", "SANJI", tmp_path, expected_duration=148.0, video_channel_url="https://youtube.com/@sample-artist"
        )

        assert result_path == mock_file
        assert diff == 15.4

    @patch("yt_song_to_instrumental.video_finder.detect_if_music_video")
    @patch("yt_song_to_instrumental.video_finder.download_source_video")
    @patch("yt_song_to_instrumental.video_finder.search_music_video_candidates")
    def test_candidate_fails_motion_check_returns_none(self, mock_search, mock_download, mock_detect, tmp_path):
        mock_search.return_value = [{"id": "mv123", "title": "Artist - Song [Visualizer]"}]
        mock_file = tmp_path / "video_mv123.mp4"
        mock_file.touch()
        mock_download.return_value = mock_file
        mock_detect.return_value = (False, 0.04)

        result_path, diff = find_and_verify_music_video(
            "Artist", "Song", tmp_path, expected_duration=180.0
        )

        assert result_path is None
        assert diff == 0.0
        assert not mock_file.exists()  # Ensure cleaned up
