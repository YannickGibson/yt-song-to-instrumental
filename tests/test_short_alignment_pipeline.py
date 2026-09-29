from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.audio_alignment import ShortAlignment
from yt_song_to_instrumental.config import LabelConfig
from yt_song_to_instrumental.constants import SHORT_ALIGNMENT_FAILED
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, _RunContext, _upload_short_track


@pytest.fixture
def short_case(tmp_path):
    release = tmp_path / "release.wav"
    release.touch()
    instrumental = tmp_path / "instrumental.wav"
    instrumental.touch()
    source = tmp_path / "source.mp4"
    source.touch()
    alternate = tmp_path / "alternate.mp4"
    alternate.touch()
    alternate_audio = tmp_path / "alternate.wav"
    alternate_audio.touch()
    history = HistoryDB(tmp_path / "history.db")
    history.record_download("source-id", "source-url", "Track", "Artist", "Album", "Artist",
                            "channel-url", str(release), "cover.jpg")
    history.record_separation("source-id", "htdemucs", str(instrumental), True, trim_start_seconds=4.0)
    history.record_upload("source-id", "htdemucs", "existing-full", "public")
    label = LabelConfig({
        "channel": {"name": "Test Instrumentals", "description": "Test"},
        "label": {"name": "Test Label"},
        "templates": {"video_title": "<artist-name> — <track-title>",
                      "video_description": "Description", "album_playlist_name": "Album",
                      "artist_playlist_name": "Artist"},
        "create_playlists_for_collaborators": False,
        "sources": [],
    })
    ctx = _RunContext(service=MagicMock(), history=history, label_config=label,
                      separator=MagicMock(), model="htdemucs", display_name="HTDemucs",
                      privacy="public", tmp_dir=tmp_path, output_dir=tmp_path,
                      upload_max_wait_seconds=None, cleanup_after_upload=False, trim_silence=False,
                      trim_silence_threshold_db=-35.0, preserve_original_video_title=False,
                      force_short=True)
    track = history.get_all_downloads()[0]
    with (
        patch("yt_song_to_instrumental.pipeline.get_source_video_title", return_value="Track"),
        patch("yt_song_to_instrumental.pipeline.download_source_video", return_value=source),
        patch("yt_song_to_instrumental.pipeline.download_track_audio", return_value=alternate_audio) as download_audio,
        patch("yt_song_to_instrumental.pipeline._get_duration", return_value=200.0),
        patch("yt_song_to_instrumental.pipeline.detect_if_music_video", return_value=(True, 30.0)) as detect,
        patch("yt_song_to_instrumental.pipeline.find_and_verify_music_video",
              return_value=(alternate, 30.0, "alternate-url")),
        patch("yt_song_to_instrumental.pipeline.align_short_audio",
              return_value=ShortAlignment(27.0, 16.0, 0.98, 0.95, 0.5)) as align,
        patch("yt_song_to_instrumental.pipeline.render_short_video") as render,
        patch("yt_song_to_instrumental.pipeline.upload_video", return_value="new-short") as upload,
    ):
        yield ctx, track, align, render, upload, detect, download_audio
    history.close()


def _run(ctx, track):
    _upload_short_track(track, "Artist", "Album", "existing-full", 4.0, ctx, PipelineReport())


def test_alternate_uses_matched_offsets_and_manages_its_soundtrack(short_case):
    ctx, track, align, render, upload, detect, download_audio = short_case
    detect.side_effect = [(False, 0.1), (True, 30.0)]
    _run(ctx, track)
    download_audio.assert_called_once_with("alternate-url", ctx.tmp_dir)
    assert align.call_args.args[0] == Path(track.audio_path)
    assert align.call_args.args[1] == ctx.tmp_dir / "video_source-id_alternate.wav"
    assert align.call_args.kwargs["audio_start_seconds"] == 16.0
    assert align.call_args.kwargs["trim_start_seconds"] == 4.0
    assert render.call_args.kwargs["start_time"] == 27.0
    assert render.call_args.kwargs["audio_start_time"] == 16.0
    assert detect.call_args.kwargs["start_time"] == 27.0
    assert ctx.history.get_upload_record(track.video_id, ctx.model).youtube_upload_id == "existing-full"
    assert ctx.history.is_short_uploaded(track.video_id, ctx.model)


def test_failed_alignment_is_retryable_and_preserves_completed_full_upload(short_case):
    ctx, track, align, render, upload, _, _ = short_case
    align.side_effect = [None, ShortAlignment(27.0, 16.0, 0.98, 0.95, 0.5)]
    _run(ctx, track)
    render.assert_not_called()
    upload.assert_not_called()
    assert ctx.history.get_short_status(track.video_id, ctx.model) == SHORT_ALIGNMENT_FAILED
    assert not ctx.history.is_short_uploaded(track.video_id, ctx.model)
    assert ctx.history.get_upload_record(track.video_id, ctx.model).youtube_upload_id == "existing-full"
    _run(ctx, track)
    assert ctx.history.is_short_uploaded(track.video_id, ctx.model)
    upload.assert_called_once()


def test_explicit_content_offset_remains_exact(short_case):
    ctx, track, align, render, _, _, _ = short_case
    ctx.short_start_seconds = 35.0
    align.return_value = ShortAlignment(45.5, 35.0, 0.98, 0.95, 0.5)
    _run(ctx, track)
    assert align.call_args.kwargs["audio_start_seconds"] == 35.0
    assert align.call_args.kwargs["exact_start"] is True
    assert render.call_args.kwargs["audio_start_time"] == 35.0
    assert render.call_args.kwargs["start_time"] == 45.5


def test_interrupted_render_does_not_commit_short_and_can_retry(short_case):
    ctx, track, _, render, upload, _, _ = short_case
    render.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        _run(ctx, track)
    upload.assert_not_called()
    assert not ctx.history.is_short_uploaded(track.video_id, ctx.model)
    render.side_effect = None
    _run(ctx, track)
    assert ctx.history.is_short_uploaded(track.video_id, ctx.model)


def test_missing_reference_or_failed_matched_window_cannot_upload(short_case):
    ctx, track, align, render, upload, detect, download_audio = short_case
    Path(track.audio_path).unlink()
    download_audio.return_value = None
    _run(ctx, track)
    align.assert_not_called()
    upload.assert_not_called()
    Path(track.audio_path).touch()
    detect.side_effect = [(True, 30.0), (False, 0.1)]
    _run(ctx, track)
    render.assert_not_called()
    upload.assert_not_called()
    assert ctx.history.get_short_status(track.video_id, ctx.model) == SHORT_ALIGNMENT_FAILED


def test_already_uploaded_short_remains_untouched(short_case):
    ctx, track, align, render, upload, _, _ = short_case
    ctx.history.record_short_upload(track.video_id, ctx.model, "existing-short")
    _run(ctx, track)
    align.assert_not_called()
    render.assert_not_called()
    upload.assert_not_called()
