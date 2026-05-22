from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from yt_song_to_instrumental.uploader import (
    _extract_error_reason,
    _retry_wait_for,
    upload_video,
)


class _FakeResp:
    def __init__(self, status, reason="Bad Request"):
        self.status = status
        self.reason = reason


def _make_http_error(reason: str, status: int = 400) -> HttpError:
    import json
    body = json.dumps({
        "error": {
            "code": status,
            "message": f"Mocked {reason}",
            "errors": [{"reason": reason, "domain": "youtube.video", "message": reason}],
        }
    }).encode("utf-8")
    return HttpError(_FakeResp(status), body)


def _fake_service_uploading(side_effect_per_call):
    """Build a fake service where videos().insert(...).next_chunk() returns the
    next side-effect per attempt. Each attempt creates a NEW request via the
    next_chunk callable, so we need to thread side effects via a counter."""
    service = MagicMock()
    counter = {"i": 0}

    def make_request(**kwargs):
        request = MagicMock()
        my_call_index = counter["i"]
        counter["i"] += 1
        effect = side_effect_per_call[my_call_index]
        if isinstance(effect, Exception):
            request.next_chunk.side_effect = effect
        else:
            request.next_chunk.return_value = (None, {"id": effect})
        return request

    service.videos.return_value.insert.side_effect = make_request
    return service


class TestExtractErrorReason:
    def test_pulls_first_reason(self):
        err = _make_http_error("uploadLimitExceeded")
        assert _extract_error_reason(err) == "uploadLimitExceeded"

    def test_returns_empty_when_no_details(self):
        # HttpError with no error_details
        err = HttpError(_FakeResp(500), b"server error")
        assert _extract_error_reason(err) == ""


class TestRetryWaitFor:
    def test_grows_exponentially(self):
        a, b, c = _retry_wait_for(1), _retry_wait_for(2), _retry_wait_for(3)
        assert a == 300
        assert b == 600
        assert c == 1200

    def test_caps_at_30_min(self):
        assert _retry_wait_for(10) == 1800
        assert _retry_wait_for(20) == 1800


class TestUploadVideoRetry:
    def test_retries_on_upload_limit_exceeded(self, tmp_path):
        f = tmp_path / "x.mp4"
        f.write_bytes(b"00")
        sleeps: list[float] = []

        service = _fake_service_uploading([
            _make_http_error("uploadLimitExceeded"),
            _make_http_error("uploadLimitExceeded"),
            "VID_OK",
        ])
        result = upload_video(
            service, f, "title", "desc", "private",
            _sleep=lambda s: sleeps.append(s),
        )
        assert result == "VID_OK"
        # Two retries → two sleeps
        assert len(sleeps) == 2
        assert sleeps[0] == 300
        assert sleeps[1] == 600

    def test_non_retryable_propagates(self, tmp_path):
        f = tmp_path / "x.mp4"
        f.write_bytes(b"00")
        service = _fake_service_uploading([_make_http_error("notFound", status=404)])
        with pytest.raises(HttpError):
            upload_video(
                service, f, "title", "desc", "private",
                _sleep=lambda s: None,
            )

    def test_max_total_wait_cap(self, tmp_path):
        f = tmp_path / "x.mp4"
        f.write_bytes(b"00")
        sleeps: list[float] = []
        # All 3 attempts hit the rate limit; cap stops us before sleeping past it.
        service = _fake_service_uploading([
            _make_http_error("uploadLimitExceeded"),
            _make_http_error("uploadLimitExceeded"),
            _make_http_error("uploadLimitExceeded"),
        ])
        # Cap = 400s. First sleep (300s) fits. Second sleep would be 600s,
        # which would push total to 900s — exceeds cap of 400s → give up before sleeping.
        with pytest.raises(HttpError):
            upload_video(
                service, f, "title", "desc", "private",
                max_total_wait_seconds=400,
                _sleep=lambda s: sleeps.append(s),
            )
        assert sleeps == [300]

    def test_first_try_success(self, tmp_path):
        f = tmp_path / "x.mp4"
        f.write_bytes(b"00")
        sleeps: list[float] = []
        service = _fake_service_uploading(["VID_OK"])
        result = upload_video(
            service, f, "title", "desc", "private",
            _sleep=lambda s: sleeps.append(s),
        )
        assert result == "VID_OK"
        assert sleeps == []
