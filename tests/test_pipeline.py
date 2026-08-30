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


class TestSingleVideoTargeting:
    def test_single_video_url_helpers(self):
        from yt_song_to_instrumental.pipeline import _extract_target_video_ids, _is_single_video_url

        assert _is_single_video_url("https://www.youtube.com/watch?v=RMzb9uyK8Q8") is True
        assert _is_single_video_url("https://youtu.be/RMzb9uyK8Q8") is True
        assert _is_single_video_url("https://music.youtube.com/watch?v=RMzb9uyK8Q8") is True
        assert _is_single_video_url("https://youtube.com/@bktherula") is False

        assert _extract_target_video_ids("https://www.youtube.com/watch?v=RMzb9uyK8Q8") == {"RMzb9uyK8Q8"}
        assert _extract_target_video_ids("https://youtu.be/RMzb9uyK8Q8") == {"RMzb9uyK8Q8"}
        assert _extract_target_video_ids("https://youtube.com/@bktherula") is None

    @patch("yt_song_to_instrumental.pipeline.download_tracks")
    @patch("yt_song_to_instrumental.pipeline.get_separator")
    def test_single_video_url_restricts_processing_to_target_id(self, mock_get_sep, mock_download, tmp_path):
        config = _make_app_config(tmp_path)
        label_config = _make_label_config()

        db = HistoryDB(db_path=":memory:")
        db.record_download("old_id", "https://yt.com/1", "Old Song", "Artist", "Album", "Chan", "ChanUrl", "old.wav", "old.jpg")
        db.record_download("target_id", "https://youtube.com/watch?v=target_id", "Target Song", "Artist", "Album", "Chan", "ChanUrl", "target.wav", "target.jpg")

        mock_download.return_value = []
        mock_sep = MagicMock()
        mock_sep.separate.return_value.instrumental_path = tmp_path / "target_inst.wav"
        mock_get_sep.return_value = mock_sep

        with patch("yt_song_to_instrumental.pipeline.check_quality") as mock_qa:
            mock_qa.return_value.passed = True
            report = process_url(
                url="https://youtube.com/watch?v=target_id",
                config=config,
                label_config=label_config,
                service=None,
                skip_upload=True,
                history=db,
            )

        assert len(report.tracks) == 1
        assert report.tracks[0].video_id == "target_id"


class TestShortsProcessing:
    @patch("yt_song_to_instrumental.pipeline.download_tracks")
    @patch("yt_song_to_instrumental.pipeline.get_separator")
    @patch("yt_song_to_instrumental.pipeline._upload_short_track")
    def test_shorts_only_skips_long_form_upload(self, mock_short_upload, mock_get_sep, mock_download, tmp_path):
        config = _make_app_config(tmp_path)
        label_config = _make_label_config()
        label_config.upload_short = True

        db = HistoryDB(db_path=":memory:")
        inst_file = tmp_path / "inst.wav"
        inst_file.write_bytes(b"RIFF" + b"\x00" * 40)
        db.record_download("v1", "https://youtube.com/watch?v=v1", "Song 1", "Artist", "Album", "Chan", "ChanUrl", "v1.wav", "v1.jpg")
        db.record_separation("v1", "htdemucs", str(inst_file), quality_passed=True, trim_start_seconds=2.5)

        mock_download.return_value = []
        mock_sep = MagicMock()
        mock_get_sep.return_value = mock_sep

        report = process_url(
            url="https://youtube.com/watch?v=v1",
            config=config,
            label_config=label_config,
            service=None,
            history=db,
            shorts_only=True,
        )

        assert mock_short_upload.call_count == 1
        call_args = mock_short_upload.call_args
        assert call_args[0][0].video_id == "v1"
        assert call_args[0][4] == 2.5  # start_time from trim_start_seconds
        assert report.uploaded == 0  # No long-form uploaded
        assert any(t.status == "short_processed" for t in report.tracks)

