from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from yt_song_to_instrumental.constants import SHORT_SOURCE_BLOCKED, SHORT_SOURCE_RESUMED
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.downloader import download_tracks
from yt_song_to_instrumental.config import Source
from yt_song_to_instrumental.source_refresh import SourceCoordinator
from yt_song_to_instrumental.pipeline import PipelineReport, _select_tracks, _upload_short_track
from yt_song_to_instrumental.video_detector import SourceVideoUnavailable, get_source_video_title


def test_empty_successful_response_is_distinct_from_transport_failure():
    service = MagicMock()
    request = service.videos.return_value.list.return_value
    request.execute.return_value = {"items": []}
    with pytest.raises(SourceVideoUnavailable):
        get_source_video_title(service, "source")
    request.execute.side_effect = ConnectionError("temporary")
    assert get_source_video_title(service, "source") is None


def test_source_block_survives_restart_without_marking_short_uploaded(tmp_path):
    database = tmp_path / "history.db"
    history = HistoryDB(database)
    history.record_download("source", "source-url", "Track", "Artist", "Album",
                            "Artist", "channel", "audio.wav", "cover.jpg")
    history.record_separation("source", "model", "instrumental.wav", True)
    history.record_upload("source", "model", "existing-full", "public")
    service = MagicMock()
    service.videos.return_value.list.return_value.execute.return_value = {"items": []}
    context = SimpleNamespace(history=history, service=service, model="model", force_short=False,
                              label_config=SimpleNamespace(upload_short=False,
                                                           upload_short_if_music_video=True))
    report = PipelineReport()
    _upload_short_track(history.get_download("source"), "Artist", "Album", "existing-full",
                        0, context, report)
    assert report.failed == 0
    history.close()

    history = HistoryDB(database)
    assert history.get_short_status("source", "model") == SHORT_SOURCE_BLOCKED
    assert not history.is_short_uploaded("source", "model")
    assert history.get_existing_upload("source").youtube_upload_id == "existing-full"
    assert _select_tracks(history, "model", False, shorts_enabled=True) == []
    history.resume_source_blocked_short("source")
    assert history.get_short_status("source", "model") == SHORT_SOURCE_RESUMED
    assert len(_select_tracks(history, "model", False, shorts_enabled=True)) == 1
    history.record_short_status("source", "model", "deleted_owner_safety")
    history.resume_source_blocked_short("source")
    assert history.get_short_status("source", "model") == "deleted_owner_safety"
    history.close()


def test_known_uploaded_song_does_not_retry_a_removed_duplicate(tmp_path, monkeypatch):
    history = HistoryDB(tmp_path / "history.db")
    history.record_download("existing", "source-url", "Track", "Artist", "Album",
                            "Artist", "channel", "audio.wav", "cover.jpg")
    history.record_upload("existing", "model", "existing-full", "public")
    extract = MagicMock(side_effect=AssertionError("must not retry duplicate"))
    monkeypatch.setattr("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", extract)
    assert download_tracks("channel", history, tmp_path, entries=[
        {"id": "unavailable", "title": "Track", "_source_channel": "Artist"}
    ]) == []
    extract.assert_not_called()
    history.close()


def test_refresh_reopens_block_only_when_source_reappears(tmp_path, monkeypatch):
    history = HistoryDB(tmp_path / "history.db")
    history.record_download("source", "source-url", "Track", "Artist", "Album",
                            "Artist", "channel", "audio.wav", "cover.jpg")
    history.record_upload("source", "model", "existing-full", "public")
    history.record_short_status("source", "model", SHORT_SOURCE_BLOCKED)
    entries = []
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.enumerate_videos",
                        lambda *args, **kwargs: entries)
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.download_tracks",
                        lambda *args, **kwargs: [])
    coordinator = SourceCoordinator([Source("channel", None)], history, tmp_path, "model", None)
    coordinator.refresh()
    assert history.get_short_status("source", "model") == SHORT_SOURCE_BLOCKED
    entries.append({"id": "source"})
    coordinator.refresh()
    assert history.get_short_status("source", "model") == SHORT_SOURCE_RESUMED
    assert not history.is_short_uploaded("source", "model")
    history.close()


@pytest.mark.parametrize("artist,title", [("Other Artist", "Track"),
                                          ("Artist", "Track (Remix)"), ("", "Track")])
def test_duplicate_filter_preserves_other_artists_and_versions(tmp_path, monkeypatch, artist, title):
    history = HistoryDB(tmp_path / "history.db")
    history.record_download("existing", "source-url", "Track", "Artist", "Album",
                            "Artist", "channel", "audio.wav", "cover.jpg")
    history.record_upload("existing", "model", "existing-full", "public")
    extractor = MagicMock()
    extractor.return_value.__enter__.return_value.extract_info.return_value = None
    monkeypatch.setattr("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", extractor)
    monkeypatch.setattr("yt_song_to_instrumental.downloader.lookup_album_index", MagicMock())
    download_tracks("channel", history, tmp_path, entries=[
        {"id": "different", "title": title, "_source_channel": artist, "url": "source-url"}
    ])
    extractor.return_value.__enter__.return_value.extract_info.assert_called_once()
    history.close()
