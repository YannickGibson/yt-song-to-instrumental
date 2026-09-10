from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.constants import (
    PRIORITY_STATUS_COMPLETED,
    PRIORITY_STATUS_FAILED,
    YOUTUBE_CANONICAL_VIDEO_URL,
)
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, TrackReport
from yt_song_to_instrumental.priority import (
    enqueue_priority_request,
    process_priority_requests,
)


def _process_pending(db: HistoryDB):
    return process_priority_requests(
        config=MagicMock(),
        label_config=MagicMock(),
        service=MagicMock(),
        history=db,
        separator=MagicMock(),
        model_name="htdemucs",
        privacy=None,
        upload_max_wait_seconds=None,
        cleanup_after_upload=True,
        trim_silence=True,
    )


class TestEnqueuePriorityRequest:
    def test_normalizes_and_persists_single_video_url(self, tmp_path):
        db_path = tmp_path / "history.db"
        request = enqueue_priority_request(
            "https://youtu.be/QueueItem01?feature=shared",
            db_path,
        )

        assert request.url == YOUTUBE_CANONICAL_VIDEO_URL.format(video_id="QueueItem01")

        db = HistoryDB(db_path)
        try:
            assert db.list_priority_requests()[0].id == request.id
        finally:
            db.close()

    def test_rejects_playlist_url(self, tmp_path):
        with pytest.raises(ValueError, match="single YouTube video URL"):
            enqueue_priority_request(
                "https://www.youtube.com/playlist?list=QueueList01",
                tmp_path / "history.db",
            )

    def test_persists_short_requirement_and_offset(self, tmp_path):
        request = enqueue_priority_request(
            "https://youtu.be/QueueItem01",
            tmp_path / "history.db",
            upload_short=True,
            short_start_seconds=35.0,
        )

        assert request.upload_short == 1
        assert request.short_start_seconds == 35.0

    def test_rejects_offset_without_short(self, tmp_path):
        with pytest.raises(ValueError, match="requires upload_short"):
            enqueue_priority_request(
                "https://youtu.be/QueueItem01",
                tmp_path / "history.db",
                short_start_seconds=35.0,
            )

    def test_rejects_negative_short_offset(self, tmp_path):
        with pytest.raises(ValueError, match="zero or greater"):
            enqueue_priority_request(
                "https://youtu.be/QueueItem01",
                tmp_path / "history.db",
                upload_short=True,
                short_start_seconds=-1.0,
            )


class TestProcessPriorityRequests:
    @patch("yt_song_to_instrumental.priority.process_url")
    def test_requires_both_outputs_and_passes_short_options(self, mock_process_url):
        db = HistoryDB(":memory:")
        request = db.enqueue_priority_request(
            "https://youtube.com/watch?v=QueueItem01",
            upload_short=True,
            short_start_seconds=35.0,
        )

        def process_both(**kwargs):
            db.record_upload("QueueItem01", "htdemucs", "long-form-id", "public")
            db.record_short_upload("QueueItem01", "htdemucs", "short-id")
            return PipelineReport(
                uploaded=1,
                tracks=[
                    TrackReport(
                        "QueueItem01", "Requested", "Sample Artist", "uploaded"
                    )
                ],
            )

        mock_process_url.side_effect = process_both

        _process_pending(db)

        call = mock_process_url.call_args.kwargs
        assert call["force_short"] is True
        assert call["short_start_seconds"] == 35.0
        saved = {item.id: item for item in db.list_priority_requests()}[request.id]
        assert saved.status == PRIORITY_STATUS_COMPLETED

    @patch("yt_song_to_instrumental.priority.process_url")
    def test_fails_requested_short_when_only_long_form_completed(self, mock_process_url):
        db = HistoryDB(":memory:")
        request = db.enqueue_priority_request(
            "https://youtube.com/watch?v=QueueItem01",
            upload_short=True,
            short_start_seconds=35.0,
        )
        db.record_upload("QueueItem01", "htdemucs", "long-form-id", "public")
        mock_process_url.return_value = PipelineReport(
            uploaded=1,
            tracks=[
                TrackReport("QueueItem01", "Requested", "Sample Artist", "uploaded")
            ],
        )

        _process_pending(db)

        saved = {item.id: item for item in db.list_priority_requests()}[request.id]
        assert saved.status == PRIORITY_STATUS_FAILED
        assert "not both completed" in saved.error

    @patch("yt_song_to_instrumental.priority.process_url")
    def test_processes_newest_first_and_marks_complete(self, mock_process_url):
        db = HistoryDB(":memory:")
        timestamps = iter((
            "2026-09-05T00:00:00+00:00",
            "2026-09-05T00:00:01+00:00",
            "2026-09-05T00:00:02+00:00",
            "2026-09-05T00:00:03+00:00",
            "2026-09-05T00:00:04+00:00",
            "2026-09-05T00:00:05+00:00",
        ))
        db._now = lambda: next(timestamps)
        first = db.enqueue_priority_request("https://youtube.com/watch?v=QueueItem01")
        second = db.enqueue_priority_request("https://youtube.com/watch?v=QueueItem02")
        mock_process_url.side_effect = (
            PipelineReport(
                uploaded=1,
                tracks=[TrackReport("QueueItem02", "Requested Two", "Artist Two", "uploaded")],
            ),
            PipelineReport(
                skipped=1,
                tracks=[TrackReport("QueueItem01", "Requested One", "Artist One", "already_uploaded")],
            ),
        )

        results = _process_pending(db)

        assert [call.kwargs["url"] for call in mock_process_url.call_args_list] == [
            second.url,
            first.url,
        ]
        assert len(results) == 2
        requests = {request.id: request for request in db.list_priority_requests()}
        assert requests[first.id].status == PRIORITY_STATUS_COMPLETED
        assert requests[second.id].status == PRIORITY_STATUS_COMPLETED

    @patch("yt_song_to_instrumental.priority.process_url")
    def test_marks_empty_pipeline_result_failed(self, mock_process_url):
        db = HistoryDB(":memory:")
        request = db.enqueue_priority_request("https://youtube.com/watch?v=QueueItem01")
        mock_process_url.return_value = PipelineReport()

        _process_pending(db)

        saved = {item.id: item for item in db.list_priority_requests()}[request.id]
        assert saved.status == PRIORITY_STATUS_FAILED
        assert saved.error
