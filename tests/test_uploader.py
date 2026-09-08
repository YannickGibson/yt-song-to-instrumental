from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from yt_song_to_instrumental.uploader import (
    _extract_error_reason,
    _retry_wait_for,
    add_video_to_playlist,
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
    def test_schedule_ladder(self):
        # 10 min → 30 min → 1 h → 2 h
        assert _retry_wait_for(1) == 600
        assert _retry_wait_for(2) == 1800
        assert _retry_wait_for(3) == 3600
        assert _retry_wait_for(4) == 7200

    def test_repeats_final_value_indefinitely(self):
        assert _retry_wait_for(5) == 7200
        assert _retry_wait_for(50) == 7200


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
        # Two retries → two sleeps (10 min, then 30 min from the schedule)
        assert len(sleeps) == 2
        assert sleeps[0] == 600
        assert sleeps[1] == 1800

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
        # Cap = 1000s. First sleep (600s = 10 min) fits (total → 600).
        # Second sleep would be 1800s (30 min), pushing total to 2400 — exceeds
        # cap → give up before sleeping a second time.
        with pytest.raises(HttpError):
            upload_video(
                service, f, "title", "desc", "private",
                max_total_wait_seconds=1000,
                _sleep=lambda s: sleeps.append(s),
            )
        assert sleeps == [600]

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


class TestAddVideoToPlaylist:
    def test_filters_for_video_before_inserting(self):
        service = MagicMock()
        playlist_items = service.playlistItems.return_value
        playlist_items.list.return_value.execute.return_value = {
            "items": [{"snippet": {"resourceId": {"videoId": "target-video"}}}],
        }

        add_video_to_playlist(service, "playlist", "target-video")

        playlist_items.list.assert_called_once_with(
            playlistId="playlist",
            part="snippet",
            videoId="target-video",
            maxResults=50,
        )
        playlist_items.insert.assert_not_called()

    def test_inserts_when_filtered_lookup_is_empty(self):
        service = MagicMock()
        playlist_items = service.playlistItems.return_value
        playlist_items.list.return_value.execute.return_value = {"items": []}

        add_video_to_playlist(service, "playlist", "target-video")

        playlist_items.insert.assert_called_once_with(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": "playlist",
                    "resourceId": {"kind": "youtube#video", "videoId": "target-video"},
                },
            },
        )
