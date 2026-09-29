from unittest.mock import MagicMock

import pytest

from tests.test_playlists import _make_label_config, _make_mock_service
from tests.test_playlist_ordering import page
from tests.test_short_alignment_pipeline import short_case, _run
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.playlists import (
    assign_to_playlists, get_or_create_shorts_playlist, queue_unassigned_shorts,
    retry_playlist_assignments,
)
from yt_song_to_instrumental.youtube_quota import QuotaLedger, QuotaReserved


def test_short_playlist_failure_preserves_upload_and_prevents_reupload(short_case):
    ctx, track, _, _, upload, _, _ = short_case
    ctx.service = _make_mock_service()
    ctx.history.record_playlist("shorts", ctx.label_config.channel_name, None, "shorts-playlist")
    ctx.service.playlistItems().insert().execute.side_effect = RuntimeError("offline")
    _run(ctx, track)
    assert ctx.history.get_short_status(track.video_id, ctx.model) == "uploaded"
    assert len(ctx.history.pending_playlist_assignments(5)) == 1
    _run(ctx, track)
    upload.assert_called_once()


def test_shorts_playlist_creation_reconciles_after_database_failure(tmp_path, monkeypatch):
    db = HistoryDB(tmp_path / "history.db")
    service = _make_mock_service("shorts-playlist")
    service.playlists().insert.reset_mock()
    service.playlists().list().execute.return_value = {"items": []}
    record = db.record_playlist
    monkeypatch.setattr(db, "record_playlist", MagicMock(side_effect=OSError("interrupted")))
    with pytest.raises(OSError):
        get_or_create_shorts_playlist(service, db, _make_label_config())
    assert service.playlists().insert.call_args.kwargs["body"]["snippet"]["title"] == "shorts"
    monkeypatch.setattr(db, "record_playlist", record)
    service.playlists().list().execute.side_effect = [
        {"items": [], "nextPageToken": "second"},
        {"items": [{"id": "shorts-playlist", "snippet": {"title": "shorts"}}]},
        {"items": [{"snippet": {"title": "shorts"}, "status": {"privacyStatus": "public"}}]},
    ]
    assert get_or_create_shorts_playlist(service, db, _make_label_config()) == "shorts-playlist"
    assert service.playlists().insert.call_count == 1


def test_old_short_and_interrupted_assignment_recover_without_duplicate(tmp_path):
    path = tmp_path / "history.db"
    db = HistoryDB(path)
    db.record_upload("source", "historical-model", "long-upload", "public")
    db.record_short_upload("source", "historical-model", "short-upload")
    db.close()
    db = HistoryDB(path)
    queue_unassigned_shorts(db)
    queue_unassigned_shorts(db)
    assert len(db.pending_playlist_assignments(10)) == 1
    service = _make_mock_service()
    db.record_playlist("shorts", _make_label_config().channel_name, None, "shorts-playlist")
    service.playlistItems().insert().execute.side_effect = TimeoutError("response lost")
    retry_playlist_assignments(service, db, _make_label_config())
    assert db.is_short_uploaded("source", "historical-model")
    assert len(db.pending_playlist_assignments(10)) == 1
    db.close()
    db = HistoryDB(path)
    # The insert succeeded remotely before the response was lost.
    service = _make_mock_service()
    service.playlistItems().list().execute.return_value = page("short-upload")
    retry_playlist_assignments(service, db, _make_label_config())
    service.playlistItems().insert.assert_not_called()
    queue_unassigned_shorts(db)
    assert db.pending_playlist_assignments(10) == []
    assert db.has_playlist_assignment("short-upload")
    assert db.get_playlist("channel", _make_label_config().channel_name) is None


def test_short_membership_failure_never_claims_completion(tmp_path):
    db = HistoryDB(tmp_path / "history.db")
    service = _make_mock_service()
    db.record_playlist("shorts", _make_label_config().channel_name, None, "shorts-playlist")
    service.playlistItems().insert().execute.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        assign_to_playlists(service, db, _make_label_config(), "short-upload", "Artist", "", "Artist", is_short=True)
    assert len(db.pending_playlist_assignments(10)) == 1
    assert not db._conn.execute("SELECT * FROM completed_playlist_assignments").fetchall()


def test_membership_borrows_unused_repair_budget_but_keeps_shared_limit(tmp_path):
    ledger = QuotaLedger(tmp_path / "quota.db")
    ledger.charge("youtube.playlistItems.insert", attempts=110)
    with ledger.membership_lane():
        ledger.charge("youtube.playlistItems.insert", attempts=80)
        with pytest.raises(QuotaReserved):
            ledger.charge("youtube.playlistItems.insert")
    with ledger.repair_lane(), pytest.raises(QuotaReserved):
        ledger.charge("youtube.playlistItems.update")
    ledger.charge("youtube.videos.insert")


def test_assignment_budget_exhaustion_preserves_remaining_work(tmp_path):
    db = HistoryDB(tmp_path / "history.db")
    for index in range(3):
        db.queue_playlist_assignment(str(index), dict(video_id=str(index), artist="Artist", album="", primary_artist="Artist"))
    service = _make_mock_service()
    service.playlistItems().list().execute.side_effect = QuotaReserved("spent")
    retry_playlist_assignments(service, db, _make_label_config())
    assert len(db.pending_playlist_assignments(10)) == 3
    service.playlistItems().insert.assert_not_called()
