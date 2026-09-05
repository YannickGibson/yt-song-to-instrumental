from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, _RunContext, _upload_short_track, process_url


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

    @patch("yt_song_to_instrumental.pipeline._upload_track")
    @patch("yt_song_to_instrumental.pipeline._separate_track", return_value=True)
    @patch("yt_song_to_instrumental.pipeline._select_tracks")
    @patch("yt_song_to_instrumental.pipeline.download_tracks", return_value=[])
    @patch("yt_song_to_instrumental.pipeline.get_separator")
    def test_checks_priority_hook_before_each_normal_track(
        self,
        mock_get_separator,
        mock_download_tracks,
        mock_select_tracks,
        mock_separate_track,
        mock_upload_track,
        tmp_path,
    ):
        config = _make_app_config(tmp_path)
        label_config = _make_label_config()
        db = HistoryDB(":memory:")
        db.record_download("QueueItem01", "url", "One", "Artist", "", "Channel", "channel-url", "one.wav", "one.jpg")
        db.record_download("QueueItem02", "url", "Two", "Artist", "", "Channel", "channel-url", "two.wav", "two.jpg")
        mock_select_tracks.return_value = db.get_all_downloads()
        before_track = MagicMock()

        process_url(
            url="https://youtube.com/@source",
            config=config,
            label_config=label_config,
            service=MagicMock(),
            history=db,
            before_track=before_track,
        )

        assert before_track.call_count == 2
        assert mock_upload_track.call_count == 2


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
        assert _is_single_video_url("https://www.youtube.com/@sample-source-16") is False

        assert _extract_target_video_ids("https://www.youtube.com/watch?v=RMzb9uyK8Q8") == {"RMzb9uyK8Q8"}
        assert _extract_target_video_ids("https://youtu.be/RMzb9uyK8Q8") == {"RMzb9uyK8Q8"}
        assert _extract_target_video_ids("https://www.youtube.com/@sample-source-16") is None

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
    @patch("yt_song_to_instrumental.pipeline.upload_video", return_value="short-id")
    @patch("yt_song_to_instrumental.pipeline.render_description", return_value="description")
    @patch("yt_song_to_instrumental.pipeline.render_short_video")
    @patch("yt_song_to_instrumental.pipeline.find_and_verify_music_video")
    @patch("yt_song_to_instrumental.pipeline.detect_if_music_video", return_value=(False, 0.1))
    @patch("yt_song_to_instrumental.pipeline.download_source_video")
    def test_short_original_link_uses_verified_alternate_music_video(
        self,
        mock_download_source,
        mock_detect,
        mock_find_music_video,
        mock_render_short,
        mock_render_description,
        mock_upload,
        tmp_path,
    ):
        source_video = tmp_path / "source.mp4"
        source_video.touch()
        alternate_video = tmp_path / "alternate.mp4"
        alternate_video.touch()
        instrumental = tmp_path / "instrumental.wav"
        instrumental.touch()
        mock_download_source.return_value = source_video
        music_video_url = "https://www.youtube.com/watch?v=musicvideo1"
        mock_find_music_video.return_value = (alternate_video, 12.0, music_video_url)

        history = MagicMock()
        history.is_short_uploaded.return_value = False
        history.get_separation_record.return_value = MagicMock(
            instrumental_path=str(instrumental),
            quality_passed=True,
            trim_start_seconds=0.0,
        )
        label_config = _make_label_config()
        label_config.upload_short_if_music_video = True
        label_config.short_description_template = (
            "Full instrumental: <full-video-url> Original video: <original-url>"
        )
        ctx = _RunContext(
            service=MagicMock(),
            history=history,
            label_config=label_config,
            separator=MagicMock(),
            model="htdemucs",
            display_name="HTDemucs",
            privacy="unlisted",
            tmp_dir=tmp_path,
            output_dir=tmp_path,
            upload_max_wait_seconds=None,
            cleanup_after_upload=False,
            trim_silence=False,
            trim_silence_threshold_db=-35.0,
            preserve_original_video_title=False,
        )
        track = MagicMock(
            video_id="source-id",
            title="Song",
            url="https://www.youtube.com/watch?v=sourceaudio",
            channel_name="Sample Artist",
            channel_url="https://www.youtube.com/@sample-artist",
        )

        _upload_short_track(
            track,
            "Sample Artist",
            "Sample Album",
            "instrumental-id",
            0.0,
            ctx,
            PipelineReport(),
        )

        assert mock_render_description.call_args.kwargs["original_url"] == music_video_url
        assert (
            mock_render_description.call_args.kwargs["full_video_url"]
            == "https://www.youtube.com/watch?v=instrumental-id"
        )

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


class TestSortTracksNewestFirst:
    def test_sorts_newest_first_and_preserves_album_track_order(self):
        from yt_song_to_instrumental.history import DownloadRecord
        from yt_song_to_instrumental.pipeline import sort_tracks_newest_first_preserve_albums

        tracks = [
            # Older Album (downloaded at 10:00:00)
            DownloadRecord("b1", "url", "Track 1", "Artist A", "Old Album", "Chan", "CUrl", "2026-09-01T10:00:00", "p", "t"),
            DownloadRecord("b2", "url", "Track 2", "Artist A", "Old Album", "Chan", "CUrl", "2026-09-01T10:00:01", "p", "t"),
            DownloadRecord("b3", "url", "Track 3", "Artist A", "Old Album", "Chan", "CUrl", "2026-09-01T10:00:02", "p", "t"),
            # Single (downloaded at 11:00:00)
            DownloadRecord("s1", "url", "New Single", "Artist A", "", "Chan", "CUrl", "2026-09-01T11:00:00", "p", "t"),
            # Newest Album (downloaded at 12:00:00)
            DownloadRecord("a1", "url", "Intro", "Artist A", "New Album", "Chan", "CUrl", "2026-09-01T12:00:00", "p", "t"),
            DownloadRecord("a2", "url", "Banger", "Artist A", "New Album", "Chan", "CUrl", "2026-09-01T12:00:01", "p", "t"),
            DownloadRecord("a3", "url", "Outro", "Artist A", "New Album", "Chan", "CUrl", "2026-09-01T12:00:02", "p", "t"),
        ]

        sorted_tracks = sort_tracks_newest_first_preserve_albums(tracks)
        expected_ids = ["a1", "a2", "a3", "s1", "b1", "b2", "b3"]
        assert [t.video_id for t in sorted_tracks] == expected_ids

    def test_release_date_wins_over_download_time(self):
        from yt_song_to_instrumental.history import DownloadRecord
        from yt_song_to_instrumental.pipeline import sort_tracks_newest_first_preserve_albums

        tracks = [
            DownloadRecord(
                "old", "url", "Old", "Artist", "", "Chan", "CUrl",
                "2026-09-05T12:00:00", "p", "t", "20230101",
            ),
            DownloadRecord(
                "new", "url", "New", "Artist", "", "Chan", "CUrl",
                "2026-09-05T10:00:00", "p", "t", "20260801",
            ),
        ]

        sorted_tracks = sort_tracks_newest_first_preserve_albums(tracks)

        assert [t.video_id for t in sorted_tracks] == ["new", "old"]
