from unittest.mock import MagicMock

import pytest

from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.playlists import assign_to_playlists, retry_playlist_assignments
from yt_song_to_instrumental.uploader import add_video_to_playlist
from tests.test_playlists import _make_label_config, _make_mock_service


def page(*ids, token=None):
    result = {"items": [{"snippet": {"resourceId": {"videoId": vid}}} for vid in ids]}
    if token:
        result["nextPageToken"] = token
    return result


@pytest.mark.parametrize("existing,new,expected", [
    (["middle", "old"], "new", 0),
    (["new", "old"], "middle", 1),
    (["new", "middle"], "old", 2),
])
def test_release_position_independent_of_upload_sequence(existing, new, expected):
    service = MagicMock()
    service.playlistItems().list().execute.return_value = page(*existing)
    add_video_to_playlist(service, "playlist", new, ranks={"new": 0, "middle": 1, "old": 2})
    assert service.playlistItems().insert.call_args.kwargs["body"]["snippet"]["position"] == expected


def test_duplicate_beyond_first_page_is_not_inserted():
    service = MagicMock()
    service.playlistItems().list().execute.side_effect = [page("other", token="next"), page("target")]
    add_video_to_playlist(service, "playlist", "target", ranks={})
    service.playlistItems().insert.assert_not_called()
    assert service.playlistItems().list.call_args.kwargs["pageToken"] == "next"


@pytest.mark.parametrize("failure", [RuntimeError("offline"), page("unknown")])
def test_failed_or_unknown_read_never_blindly_appends(failure):
    service = MagicMock()
    if isinstance(failure, Exception):
        service.playlistItems().list().execute.side_effect = failure
    else:
        service.playlistItems().list().execute.return_value = failure
    with pytest.raises((RuntimeError, ValueError)):
        add_video_to_playlist(service, "playlist", "new", ranks={"new": 0})
    service.playlistItems().insert.assert_not_called()


def test_partial_assignment_survives_restart_and_retries(tmp_path):
    path = tmp_path / "history.db"
    db = HistoryDB(path)
    service = _make_mock_service()
    service.playlistItems().insert().execute.side_effect = [dict(id="item"), RuntimeError("offline")]
    with pytest.raises(RuntimeError):
        assign_to_playlists(service, db, _make_label_config(), "upload", "Artist", "", "Artist")
    assert len(db.pending_playlist_assignments(5)) == 1
    db.close()
    db = HistoryDB(path)
    # The first target already contains the upload; recovery must not duplicate it.
    service = _make_mock_service()
    service.playlistItems().list().execute.side_effect = [page("upload"), page()]
    retry_playlist_assignments(service, db, _make_label_config())
    assert service.playlistItems().insert.call_count == 1
    assert db.pending_playlist_assignments(5) == []
    db.close()


def test_assignment_uses_persisted_release_order():
    db = HistoryDB(":memory:")
    for source, date in [("old", "2020-01-01"), ("new", "2025-01-01")]:
        db.record_download(source, "", source, "Artist", "", "Artist", "", "", "", release_date=date)
        db.record_upload(source, "model", source + "-upload", "private")
    service = _make_mock_service()
    service.playlistItems().list().execute.return_value = page("old-upload")
    assign_to_playlists(service, db, _make_label_config(), "new-upload", "Artist", "", "Artist")
    for call in service.playlistItems().insert.call_args_list:
        assert call.kwargs["body"]["snippet"]["position"] == 0


def test_existing_inversions_queue_instead_of_adding_more_disorder():
    service = MagicMock()
    service.playlistItems().list().execute.return_value = page("old", "new")
    with pytest.raises(ValueError, match="existing order"):
        add_video_to_playlist(service, "playlist", "middle", ranks={"new": 0, "middle": 1, "old": 2})
    service.playlistItems().insert.assert_not_called()
