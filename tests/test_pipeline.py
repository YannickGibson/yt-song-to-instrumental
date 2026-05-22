from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, process_url


def _make_label_config() -> LabelConfig:
    return LabelConfig({
        "channel": {"name": "Test Instrumentals", "description": "Test"},
        "label": {"name": "TestLabel"},
        "templates": {
            "video_title": "<artist-name> — <track-title> (Instrumental)",
            "video_description": "Desc for <track-title>",
            "album_playlist_name": "<artist-name> — <album-name> Instrumentals",
            "artist_playlist_name": "<artist-name> Instrumentals",
        },
        "create_playlists_for_collaborators": True,
        "sources": [],
    })


def _make_app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        separator_model="htdemucs",
        output_dir=str(tmp_path / "output"),
        tmp_dir=str(tmp_path / "tmp"),
        db_path=":memory:",
        default_privacy="unlisted",
    )


class TestProcessUrlHistoryLifecycle:
    @patch("yt_song_to_instrumental.pipeline.download_tracks")
    @patch("yt_song_to_instrumental.pipeline.get_separator")
    def test_caller_owned_history_is_not_closed(self, mock_get_sep, mock_download, tmp_path):
        config = _make_app_config(tmp_path)
        label_config = _make_label_config()
        mock_download.return_value = []
        mock_get_sep.return_value = MagicMock()

        db = HistoryDB(db_path=":memory:")
        process_url(
            url="https://youtube.com/watch?v=test",
            config=config,
            label_config=label_config,
            service=None,
            skip_upload=True,
            history=db,
        )

        # Caller-owned history must remain open for subsequent calls.
        assert db.is_downloaded("nonexistent") is False


class TestProcessUrlSkipUpload:
    @patch("yt_song_to_instrumental.pipeline.download_tracks")
    @patch("yt_song_to_instrumental.pipeline.get_separator")
    def test_skip_upload_separates_but_does_not_upload(self, mock_get_sep, mock_download, tmp_path):
        config = _make_app_config(tmp_path)
        label_config = _make_label_config()

        mock_download.return_value = []
        mock_separator = MagicMock()
        mock_get_sep.return_value = mock_separator

        report = process_url(
            url="https://youtube.com/watch?v=test",
            config=config,
            label_config=label_config,
            service=None,
            skip_upload=True,
        )

        assert report.uploaded == 0


class TestPipelineReport:
    def test_default_values(self):
        report = PipelineReport()
        assert report.downloaded == 0
        assert report.separated == 0
        assert report.uploaded == 0
        assert report.skipped == 0
        assert report.failed == 0
        assert report.tracks == []
