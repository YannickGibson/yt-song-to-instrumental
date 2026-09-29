from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.config import AppConfig, LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import process_url
from yt_song_to_instrumental.upload_pacing import wait_for_upload_slot


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc), "sleeps": []}

    def sleep(seconds):
        state["sleeps"].append(seconds)
        state["now"] += timedelta(seconds=seconds)

    mock_datetime = MagicMock()
    mock_datetime.now.side_effect = lambda tz: state["now"]
    monkeypatch.setattr("yt_song_to_instrumental.upload_pacing.datetime", mock_datetime)
    monkeypatch.setattr("yt_song_to_instrumental.upload_pacing.time.sleep", sleep)
    monkeypatch.setattr(HistoryDB, "_now", lambda self: state["now"].isoformat())
    return state


@pytest.fixture
def label_data():
    return {
        "channel": {"name": "Test", "description": "Test"},
        "label": {"name": "Test Label"},
        "templates": {
            "video_title": "<artist-name> — <track-title>",
            "video_description": "Description",
            "album_playlist_name": "Album",
            "artist_playlist_name": "Artist",
        },
        "create_playlists_for_collaborators": False,
        "sources": [],
    }


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "1200", {}])
def test_invalid_interval_is_rejected(label_data, value):
    label_data["upload_interval_seconds"] = value
    with pytest.raises(ValueError, match="upload_interval_seconds"):
        LabelConfig(label_data)


def test_interval_is_optional_and_accepts_seconds(label_data):
    assert LabelConfig(label_data).upload_interval_seconds == 0
    label_data["upload_interval_seconds"] = 1200
    assert LabelConfig(label_data).upload_interval_seconds == 1200


def test_shared_interval_survives_reopening_history_and_model_changes(tmp_path, clock):
    path = tmp_path / "history.db"
    history = HistoryDB(path)
    history.record_upload("first", "htdemucs", "full-id", "public")
    clock["now"] += timedelta(seconds=60)
    history.record_short_upload("first", "htdemucs", "short-id")
    latest = clock["now"]
    clock["now"] += timedelta(seconds=300)
    history.record_short_status("failed", "mel_gabox_instv7n", "upload_failed")
    history.close()

    recovered = HistoryDB(path)
    assert recovered.latest_upload_time() == latest
    wait_for_upload_slot(recovered, 1200)
    assert clock["sleeps"] == [900]
    recovered.record_upload("second", "mel_gabox_instv7n", "second-id", "public")
    wait_for_upload_slot(recovered, 1200)
    assert clock["sleeps"] == [900, 1200]
    assert recovered.is_short_uploaded("first", "htdemucs")
    recovered.close()


def test_empty_history_disabled_pacing_and_no_catchup_burst(clock):
    history = HistoryDB(":memory:")
    wait_for_upload_slot(history, 1200)
    history.record_upload("first", "htdemucs", "first-id", "public")
    wait_for_upload_slot(history, 0)
    clock["now"] += timedelta(hours=2)
    wait_for_upload_slot(history, 1200)
    assert clock["sleeps"] == []
    history.record_upload("next", "htdemucs", "next-id", "public")
    wait_for_upload_slot(history, 1200)
    assert clock["sleeps"] == [1200]
    history.close()


def test_rechecks_time_after_early_wakeup(clock):
    history = HistoryDB(":memory:")
    history.record_upload("first", "htdemucs", "first-id", "public")

    def wake(seconds):
        clock["sleeps"].append(seconds)
        clock["now"] += timedelta(seconds=seconds / 2 if len(clock["sleeps"]) == 1 else seconds)

    with patch("yt_song_to_instrumental.upload_pacing.time.sleep", side_effect=wake):
        wait_for_upload_slot(history, 1200)
    assert clock["sleeps"] == [1200, 600]
    history.close()


def test_stopped_wait_preserves_remaining_delay(tmp_path, clock):
    path = tmp_path / "history.db"
    history = HistoryDB(path)
    history.record_upload("first", "htdemucs", "first-id", "public")
    with patch("yt_song_to_instrumental.upload_pacing.time.sleep", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            wait_for_upload_slot(history, 1200)
    history.close()
    clock["now"] += timedelta(seconds=500)
    recovered = HistoryDB(path)
    wait_for_upload_slot(recovered, 1200)
    assert clock["sleeps"] == [700]
    assert len(recovered.get_all_uploads()) == 1
    recovered.close()


def test_pipeline_waits_before_upload_and_keeps_interrupted_track_retryable(tmp_path, clock, label_data):
    label_data["upload_interval_seconds"] = 1200
    label = LabelConfig(label_data)
    config = AppConfig(output_dir=str(tmp_path), tmp_dir=str(tmp_path), separator_model="htdemucs")
    history = HistoryDB(tmp_path / "history.db")
    audio = tmp_path / "audio.wav"
    cover = tmp_path / "cover.jpg"
    audio.touch()
    cover.touch()
    history.record_download("pending", "url", "Track", "Artist", "Album", "Artist",
                            "channel-url", str(audio), str(cover))
    history.record_separation("pending", "htdemucs", str(audio), True)
    history.record_upload("previous", "htdemucs", "previous-id", "public")

    with (
        patch("yt_song_to_instrumental.pipeline.render_video"),
        patch("yt_song_to_instrumental.pipeline.get_thumbnail_for_track", return_value=cover),
        patch("yt_song_to_instrumental.pipeline.assign_to_playlists"),
        patch("yt_song_to_instrumental.pipeline.repair_due"),
        patch("yt_song_to_instrumental.pipeline.upload_video", return_value="new-id") as upload,
    ):
        def run():
            return process_url("https://youtube.com/@sample-source", config, label, MagicMock(),
                               skip_download=True, history=history, separator=MagicMock(),
                               cleanup_after_upload=False)

        with patch("yt_song_to_instrumental.upload_pacing.time.sleep", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                run()
        upload.assert_not_called()
        assert not history.is_uploaded("pending", "htdemucs")
        assert history.is_separated("pending", "htdemucs")

        report = run()
        assert clock["sleeps"] == [1200]
        upload.assert_called_once()
        assert report.uploaded == 1
        assert history.is_uploaded("pending", "htdemucs")
    history.close()
