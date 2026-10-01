from pathlib import Path
from unittest.mock import MagicMock

import pytest

from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, _RunContext, _upload_track, process_url


@pytest.fixture
def history():
    db = HistoryDB(":memory:")
    db.record_download(
        "PastTrack01", "https://youtube.com/watch?v=PastTrack01", "Past Track",
        "Example Artist", "", "Channel", "channel-url", "missing.wav", "missing.jpg",
    )
    yield db
    db.close()


@pytest.fixture
def config(tmp_path):
    return AppConfig(
        separator_model="new-model", output_dir=str(tmp_path / "output"),
        tmp_dir=str(tmp_path / "tmp"), db_path=":memory:", default_privacy="unlisted",
    )


@pytest.fixture
def label():
    return LabelConfig({
        "channel": {"name": "Example Instrumentals", "description": "Example"},
        "label": {"name": "Example Label"},
        "templates": {
            "video_title": "<artist-name> — <track-title> (Instrumental)",
            "video_description": "Description for <track-title>",
            "album_playlist_name": "<artist-name> — <album-name> Instrumentals",
            "artist_playlist_name": "<artist-name> Instrumentals",
        },
        "sources": [],
        "create_playlists_for_collaborators": True,
    })


@pytest.fixture(autouse=True)
def no_playlist_network(monkeypatch):
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.repair_due", MagicMock())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.retry_playlist_assignments", MagicMock())


def test_model_switch_does_not_separate_or_reupload_published_catalog(history, config, label, monkeypatch):
    history.record_upload("PastTrack01", "htdemucs", "Original001", "public")
    separate = MagicMock()
    upload = MagicMock()
    monkeypatch.setattr("yt_song_to_instrumental.pipeline._separate_track", separate)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.upload_video", upload)

    report = process_url(
        "https://youtube.com/@example", config, label, None, history=history,
        separator=MagicMock(), skip_download=True,
    )

    separate.assert_not_called()
    upload.assert_not_called()
    assert report.uploaded == 0
    assert history.get_upload_record("PastTrack01", "new-model") is None


def test_historical_short_keeps_original_model_link_trim_and_record(history, config, label, monkeypatch):
    history.record_upload("PastTrack01", "htdemucs", "Original001", "public")
    history.record_separation("PastTrack01", "htdemucs", "old.wav", True, trim_start_seconds=2.5)
    label.upload_short = True
    historical_separator = MagicMock()
    get_separator = MagicMock(return_value=historical_separator)
    separate = MagicMock()
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.get_separator", get_separator)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline._separate_track", separate)

    def complete_short(track, artist, album, long_form_id, start_time, context, report):
        assert long_form_id == "Original001"
        assert start_time == 2.5
        assert context.model == "htdemucs"
        assert context.separator is historical_separator
        context.history.record_short_upload(track.video_id, context.model, "OriginalShort")

    short = MagicMock(side_effect=complete_short)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline._upload_short_track", short)

    process_url(
        "https://youtube.com/@example", config, label, None, history=history,
        separator=MagicMock(), skip_download=True, cleanup_after_upload=False,
    )

    separate.assert_not_called()
    get_separator.assert_called_once_with("htdemucs")
    short.assert_called_once()
    assert history.get_existing_upload("PastTrack01").youtube_short_upload_id == "OriginalShort"
    assert history.get_upload_record("PastTrack01", "new-model") is None


def test_final_upload_guard_blocks_new_model_even_with_finished_separation(history, config, label, monkeypatch):
    history.record_upload("PastTrack01", "htdemucs", "Original001", "public")
    history.record_separation("PastTrack01", "new-model", "new.wav", True)
    upload = MagicMock()
    render = MagicMock()
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.upload_video", upload)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.render_video", render)
    context = _RunContext(
        service=None, history=history, label_config=label, separator=MagicMock(),
        model="new-model", display_name="New Model", privacy="public",
        tmp_dir=Path(config.tmp_dir), output_dir=Path(config.output_dir),
        upload_max_wait_seconds=None, cleanup_after_upload=False,
        trim_silence=False, trim_silence_threshold_db=-35.0,
        preserve_original_video_title=False,
    )
    report = PipelineReport()

    _upload_track(history.get_download("PastTrack01"), "Example Artist", "", context, report)

    upload.assert_not_called()
    render.assert_not_called()
    assert report.tracks[0].status == "already_uploaded"
    assert len(history.get_all_uploads()) == 1


def test_priority_completion_during_track_hook_prevents_stale_selected_upload(history, config, label, monkeypatch):
    separate = MagicMock()
    upload = MagicMock()
    monkeypatch.setattr("yt_song_to_instrumental.pipeline._separate_track", separate)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.upload_video", upload)

    def finish_priority():
        history.record_upload("PastTrack01", "htdemucs", "Original001", "public")

    report = process_url(
        "https://youtube.com/@example", config, label, None, history=history,
        separator=MagicMock(), skip_download=True, cleanup_after_upload=False,
        before_track=finish_priority,
    )

    separate.assert_not_called()
    upload.assert_not_called()
    assert report.tracks[0].status == "already_uploaded"
