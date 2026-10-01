from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, _separate_track, _upload_short_track
from yt_song_to_instrumental.constants import SHORT_RETRYABLE_FAILURE


def test_missing_separation_output_regenerates_without_deleting_history(tmp_path, monkeypatch):
    db = HistoryDB(tmp_path / "history.db")
    db.record_separation("source", "model", str(tmp_path / "lost.wav"), True)
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"source")
    output = tmp_path / "recovered.wav"
    output.write_bytes(b"complete output")
    separator = Mock()
    separator.separate.return_value = SimpleNamespace(instrumental_path=output)
    ctx = SimpleNamespace(history=db, model="model", separator=separator, output_dir=tmp_path,
                          tmp_dir=tmp_path, display_name="Example", trim_silence=False)
    track = SimpleNamespace(video_id="source", title="Example", audio_path=str(audio))
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.check_quality", lambda path: SimpleNamespace(passed=True))
    report = PipelineReport()
    assert _separate_track(track, "Example Artist", ctx, report)
    assert db.get_separation_record("source", "model").instrumental_path == str(output)
    assert report.separated == 1
    separator.separate.assert_called_once()
    # Complete durable outputs do not run the model again.
    assert _separate_track(track, "Example Artist", ctx, report)
    separator.separate.assert_called_once()
    db.close()


@pytest.mark.parametrize("status", ["render_failed", "upload_failed", "source_video_download_failed"])
def test_short_failures_reach_worker_exit_report(tmp_path, monkeypatch, status):
    db = HistoryDB(tmp_path / "history.db")
    db.record_upload("source", "model", "full-upload", "private")
    ctx = SimpleNamespace(history=db, model="model", force_short=False,
                          label_config=SimpleNamespace(upload_short=True, upload_short_if_music_video=False))
    track = SimpleNamespace(video_id="source", title="Example")
    monkeypatch.setattr("yt_song_to_instrumental.pipeline._perform_short_track",
                        lambda *args: db.record_short_status("source", "model", status))
    report = PipelineReport()
    _upload_short_track(track, "Example Artist", "Example Album", "full-upload", 0, ctx, report)
    assert report.failed == 1
    assert report.tracks[0].status == SHORT_RETRYABLE_FAILURE
    assert db.get_existing_upload("source").youtube_upload_id == "full-upload"
    db.close()
