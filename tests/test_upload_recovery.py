import json
from pathlib import Path
from unittest.mock import Mock

import httplib2
import pytest
from googleapiclient.http import HttpRequest, MediaFileUpload

from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.upload_recovery import Journal, recovered_attempt, reconcile_expired, upload_journal


BODY = {"snippet": {"title": "Example Track", "description": "Example description"}}


def response(status, **headers):
    return httplib2.Response({"status": str(status), **headers})


def request(transport, media):
    return HttpRequest(transport, lambda resp, content: json.loads(content),
                       "https://example.invalid/upload", method="POST", body=json.dumps(BODY),
                       resumable=MediaFileUpload(str(media), mimetype="video/mp4", chunksize=4, resumable=True))


@pytest.fixture
def upload(tmp_path):
    db = HistoryDB(tmp_path / "history.db")
    media = tmp_path / "media.mp4"
    media.write_bytes(b"abcdefgh")
    yield db, media
    db.close()


def test_session_durable_before_first_byte_and_result_before_return(upload):
    db, media = upload
    calls = []

    def send(uri, method, body=None, headers=None):
        calls.append(method)
        if method == "POST":
            return response(200, location="https://example.invalid/session"), b""
        journal = Journal(db._conn, "source", "model", "instrumental")
        assert journal.value["session"] == uri
        if len(calls) == 2:
            return response(308, range="bytes=0-3"), b""
        return response(200), b'{"id":"completed"}'

    transport = Mock(request=send)
    with upload_journal(db, "source", "model", "instrumental"):
        assert recovered_attempt(Mock(), request(transport, media), media, BODY) == "completed"
    assert Journal(db._conn, "source", "model", "instrumental").value["result"] == "completed"
    # Simulate a crash before HistoryDB.record_upload: no second HTTP insert.
    transport = Mock()
    with upload_journal(db, "source", "model", "instrumental"):
        assert recovered_attempt(Mock(), request(transport, media), media, BODY) == "completed"
    transport.request.assert_not_called()


def test_lost_final_response_queries_existing_session(upload):
    db, media = upload
    transport = Mock()
    transport.request.side_effect = [(response(200, location="https://example.invalid/session"), b""), ConnectionError("lost response")]
    with upload_journal(db, "source", "model", "short"):
        with pytest.raises(ConnectionError):
            recovered_attempt(Mock(), request(transport, media), media, BODY)
    transport = Mock()
    transport.request.return_value = response(200), b'{"id":"remote-complete"}'
    with upload_journal(db, "source", "model", "short"):
        assert recovered_attempt(Mock(), request(transport, media), media, BODY) == "remote-complete"
    assert transport.request.call_count == 1
    assert transport.request.call_args.kwargs["method"] == "PUT"
    assert transport.request.call_args.kwargs["headers"]["Content-Range"] == "bytes */*"


def test_interrupted_chunk_resumes_at_server_offset(upload):
    db, media = upload
    transport = Mock()
    transport.request.side_effect = [
        (response(200, location="https://example.invalid/session"), b""),
        (response(308, range="bytes=0-3"), b""), ConnectionError("interrupted"),
    ]
    with upload_journal(db, "source", "model", "instrumental"):
        with pytest.raises(ConnectionError):
            recovered_attempt(Mock(), request(transport, media), media, BODY)
    transport = Mock()
    transport.request.side_effect = [(response(308, range="bytes=0-3"), b""), (response(200), b'{"id":"resumed"}')]
    with upload_journal(db, "source", "model", "instrumental"):
        assert recovered_attempt(Mock(), request(transport, media), media, BODY) == "resumed"
    assert transport.request.call_args.kwargs["headers"]["Content-Range"] == "bytes 4-7/8"


def channel_service(items):
    service = Mock()
    service.channels.return_value.list.return_value.execute.return_value = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]}
    service.playlistItems.return_value.list.return_value.execute.return_value = {"items": [{"contentDetails": {"videoId": "completed"}}]}
    service.videos.return_value.list.return_value.execute.return_value = {"items": items}
    return service


def test_expired_session_reconciles_remote_success(upload):
    db, _ = upload
    journal = Journal(db._conn, "source", "model", "short")
    journal.save(body=BODY, started=0, session="expired")
    service = channel_service([{"id": "completed", "snippet": dict(BODY["snippet"], publishedAt="2026-01-01T00:00:00Z")}])
    assert reconcile_expired(service, journal) == "completed"
    assert journal.value["result"] == "completed"


def test_expired_session_requires_successful_reads_and_visibility_grace(upload, monkeypatch):
    db, _ = upload
    journal = Journal(db._conn, "source", "model", "short")
    journal.save(body=BODY, started=0, session="expired")
    service = channel_service([])
    monkeypatch.setattr("yt_song_to_instrumental.upload_recovery.time.time", lambda: 1000)
    with pytest.raises(RuntimeError, match="awaiting"):
        reconcile_expired(service, journal)
    assert journal.value["session"] == "expired"
    monkeypatch.setattr("yt_song_to_instrumental.upload_recovery.time.time", lambda: 2000)
    service.videos.return_value.list.return_value.execute.side_effect = ConnectionError()
    with pytest.raises(ConnectionError):
        reconcile_expired(service, journal)
    assert journal.value["session"] == "expired"
    service.videos.return_value.list.return_value.execute.side_effect = None
    assert reconcile_expired(service, journal) is None
    assert journal.value["session"] is None


def test_failed_priority_requests_retry_once_per_worker_preserving_outputs(upload):
    db, _ = upload
    req = db.enqueue_priority_request("https://www.youtube.com/watch?v=Example0001", upload_short=True, short_start_seconds=12)
    db.claim_next_priority_request()
    db.record_upload("Example0001", "model", "existing", "private")
    db.fail_priority_request(req.id, "render failed", retryable=True)
    assert db.claim_next_priority_request() is None
    assert db.requeue_failed_priority_requests() == 1
    recovered = db.claim_next_priority_request()
    assert recovered.upload_short and recovered.short_start_seconds == 12
    assert db.get_existing_upload("Example0001").youtube_upload_id == "existing"


def test_terminal_priority_failures_are_not_requeued(upload):
    db, _ = upload
    request = db.enqueue_priority_request("https://www.youtube.com/watch?v=Example0001")
    db.fail_priority_request(request.id, "terminal rejection")
    assert db.requeue_failed_priority_requests() == 0
    assert db.claim_next_priority_request() is None


def test_ambiguous_external_uploads_never_reinsert(upload):
    db, _ = upload
    journal = Journal(db._conn, "source", "model", "instrumental")
    journal.save(body=BODY, started=0, session="expired")
    snippet = dict(BODY["snippet"], publishedAt="2026-01-01T00:00:00Z")
    with pytest.raises(RuntimeError, match="Ambiguous"):
        reconcile_expired(channel_service([{"id": "first", "snippet": snippet}, {"id": "second", "snippet": snippet}]), journal)
    assert journal.value["session"] == "expired"
