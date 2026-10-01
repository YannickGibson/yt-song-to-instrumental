from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yt_song_to_instrumental.config import AppConfig, LabelConfig, Source
from yt_song_to_instrumental.downloader import download_tracks
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import PipelineReport, TrackReport, _admit_upload, _upload_short_track, process_url
from yt_song_to_instrumental.source_refresh import SourceCoordinator
from yt_song_to_instrumental.upload_pacing import UploadDeferred, is_recent_release, wait_for_upload_slot


def label():
    return LabelConfig({
        "channel": {"name": "Example", "description": "Example"},
        "label": {"name": "Example"},
        "templates": {"video_title": "<track-title>", "video_description": "Example",
                      "album_playlist_name": "<album-name>", "artist_playlist_name": "<artist-name>"},
        "create_playlists_for_collaborators": False, "sources": [],
        "upload_interval_seconds": 7200, "upload_interval_jitter_seconds": 1800,
    })


def add_track(db, tmp_path, video_id, days_ago):
    release = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y%m%d")
    audio = tmp_path / (video_id + ".wav")
    thumbnail = tmp_path / (video_id + ".jpg")
    audio.touch()
    thumbnail.touch()
    db.record_download(video_id, "https://www.youtube.com/watch?v=" + video_id,
                       video_id, "Example Artist", "", "Example Artist", "example-channel",
                       str(audio), str(thumbnail), release_date=release)
    db.record_separation(video_id, "htdemucs", str(audio), True)
    return db.get_download(video_id)


@pytest.fixture
def queue(tmp_path):
    db = HistoryDB(tmp_path / "history.db")
    sources = [Source("https://example.invalid/first", None),
               Source("https://example.invalid/second", None, create_album_playlists=False)]
    cfg = label()
    coordinator = SourceCoordinator(sources, db, tmp_path, "htdemucs", cfg)
    yield db, cfg, coordinator
    db.close()


@pytest.mark.parametrize("days,expected", [(0, True), (6, True), (30, True), (31, False), (-1, False)])
def test_recent_release_boundary(days, expected):
    release = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")
    assert is_recent_release(release, 30) is expected


@pytest.mark.parametrize("release", ["", "invalid", "20261301", None])
def test_unknown_dates_do_not_bypass_pacing(release):
    assert not is_recent_release(release, 30)


def test_recent_batch_can_be_disabled():
    assert not is_recent_release(datetime.now(timezone.utc).strftime("%Y%m%d"), 0)


@pytest.mark.parametrize("window", [-1, True, 1.5, "30"])
def test_recent_window_validation(window):
    cfg = {"channel": {"name": "Example", "description": "Example"}, "label": {"name": "Example"}, "templates": {
        "video_title": "<track-title>", "video_description": "Example",
        "album_playlist_name": "<album-name>", "artist_playlist_name": "<artist-name>"},
        "recent_upload_window_days": window, "create_playlists_for_collaborators": False, "sources": []}
    with pytest.raises(ValueError, match="recent_upload_window_days"):
        LabelConfig(cfg)


def test_refresh_visits_every_source_and_persists_source_policy(queue, tmp_path, monkeypatch):
    db, cfg, coordinator = queue
    seen = []
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.enumerate_videos",
                        lambda url, **kwargs: [{"id": "SourceItem1" if url.endswith("first") else "SourceItem2"}])

    def download(url, history, folder, **kwargs):
        seen.append(url)
        item = kwargs["entries"][0]["id"]
        add_track(history, folder, item, 2)
        return [item]

    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.download_tracks", download)
    coordinator.refresh()
    assert seen == [s.url for s in coordinator.sources]
    reopened = HistoryDB(db._db_path)
    assert reopened.source_memberships("SourceItem2") == {(coordinator.sources[1].url, "videos")}
    reopened.close()
    assert coordinator.source_for(db.get_download("SourceItem2")).create_album_playlists is False


def test_scan_failure_does_not_skip_other_sources(queue, monkeypatch):
    _, _, coordinator = queue
    def enumerate_source(url, **kwargs):
        if url.endswith("first"):
            raise ConnectionError("temporary")
        return []
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.enumerate_videos", enumerate_source)
    download = Mock(return_value=[])
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.download_tracks", download)
    coordinator.refresh()
    assert coordinator.failed_sources == {coordinator.sources[0]}
    assert download.call_args.args[0] == coordinator.sources[1].url


def test_new_release_preempts_prepared_old_track(queue, tmp_path, monkeypatch):
    db, _, coordinator = queue
    old = add_track(db, tmp_path, "OldTrack001", 60)
    monkeypatch.setattr(coordinator, "refresh", lambda: add_track(db, tmp_path, "NewTrack001", 1))
    with pytest.raises(UploadDeferred):
        coordinator.before_upload(old)
    assert db.get_separation_record(old.video_id, "htdemucs").quality_passed
    assert coordinator.candidates()[0].video_id == "NewTrack001"


def test_pending_priority_preempts_normal_but_not_its_own_upload(queue, tmp_path, monkeypatch):
    db, _, coordinator = queue
    track = add_track(db, tmp_path, "NewTrack001", 1)
    db.enqueue_priority_request("https://www.youtube.com/watch?v=QueueItem01", upload_short=True, short_start_seconds=12)
    monkeypatch.setattr(coordinator, "refresh", Mock())
    with pytest.raises(UploadDeferred):
        coordinator.before_upload(track)
    coordinator.before_upload(track, priority_request=True)
    assert coordinator.refresh.call_count == 2


def test_recent_upload_bypasses_wait_but_always_refreshes(queue, tmp_path, monkeypatch):
    db, cfg, coordinator = queue
    recent = add_track(db, tmp_path, "NewTrack001", 6)
    refresh = Mock()
    monkeypatch.setattr(coordinator, "refresh", refresh)
    wait = Mock()
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.wait_for_upload_slot", wait)
    ctx = SimpleNamespace(coordinator=coordinator, priority_request=False, label_config=cfg, history=db)
    _admit_upload(recent, ctx)
    refresh.assert_called_once()
    wait.assert_not_called()


def test_old_upload_retains_pacing_and_refresh_callback(queue, tmp_path, monkeypatch):
    db, cfg, coordinator = queue
    old = add_track(db, tmp_path, "OldTrack001", 60)
    monkeypatch.setattr(coordinator, "refresh", Mock())
    wait = Mock(side_effect=lambda *args, **kwargs: kwargs["check"]())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.wait_for_upload_slot", wait)
    _admit_upload(old, SimpleNamespace(coordinator=coordinator, priority_request=False, label_config=cfg, history=db))
    assert wait.call_args.args == (db, 7200, 1800)
    coordinator.refresh.assert_called_once()


def test_pacing_wait_refreshes_again_and_can_yield_to_new_work(queue, monkeypatch):
    db, _, _ = queue
    db.record_upload("previous", "htdemucs", "published", "public")
    check = Mock(side_effect=[None, UploadDeferred()])
    sleep = Mock()
    monkeypatch.setattr("yt_song_to_instrumental.upload_pacing.time.sleep", sleep)
    with pytest.raises(UploadDeferred):
        wait_for_upload_slot(db, 7200, 1800, check=check)
    assert sleep.call_args.args[0] == 900
    assert check.call_count == 2


def test_known_downloads_skip_metadata_and_catalog_work(queue, tmp_path, monkeypatch):
    db, _, _ = queue
    add_track(db, tmp_path, "OldTrack001", 60)
    lookup = Mock()
    monkeypatch.setattr("yt_song_to_instrumental.downloader.lookup_video_date", lookup)
    monkeypatch.setattr("yt_song_to_instrumental.downloader.lookup_album_index", lookup)
    assert download_tracks("example", db, tmp_path, after_date="20000101", entries=[{"id": "OldTrack001"}]) == []
    lookup.assert_not_called()


def test_managed_pipeline_reselects_new_track_before_upload_and_does_not_repeat(queue, tmp_path, monkeypatch):
    db, cfg, coordinator = queue
    add_track(db, tmp_path, "OldTrack001", 60)
    refresh_count = []
    def refresh():
        refresh_count.append(True)
        if not db.is_downloaded("NewTrack001"):
            add_track(db, tmp_path, "NewTrack001", 1)
    monkeypatch.setattr(coordinator, "refresh", refresh)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.queue_unassigned_shorts", Mock())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.retry_playlist_assignments", Mock())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.repair_due", Mock())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.assign_to_playlists", Mock())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.get_thumbnail_for_track", lambda video_id, path, folder: path)
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.render_video", Mock())
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.wait_for_upload_slot", lambda *args, **kwargs: kwargs["check"]())
    uploaded = []
    def upload(service, path, title, *args, **kwargs):
        uploaded.append(title)
        return "uploaded-" + title
    monkeypatch.setattr("yt_song_to_instrumental.pipeline.upload_video", upload)
    report = process_url("https://example.invalid/first", AppConfig(output_dir=str(tmp_path), tmp_dir=str(tmp_path)),
                         cfg, Mock(), history=db, separator=Mock(), coordinator=coordinator, cleanup_after_upload=False)
    assert uploaded == ["NewTrack001", "OldTrack001"]
    assert report.uploaded == 2 and report.failed == 0
    assert len(refresh_count) == 3
    assert db.get_existing_upload("OldTrack001")


def test_intentionally_deferred_short_is_not_reported_as_failure(queue, tmp_path, monkeypatch):
    db, cfg, coordinator = queue
    cfg.upload_short = True
    recent = add_track(db, tmp_path, "NewTrack001", 1)
    db.record_upload(recent.video_id, "htdemucs", "full-upload", "public")
    monkeypatch.setattr("yt_song_to_instrumental.pipeline._perform_short_track", Mock(side_effect=UploadDeferred()))
    report = PipelineReport()
    with pytest.raises(UploadDeferred):
        _upload_short_track(recent, recent.artist, recent.album, "full-upload", 0,
                            SimpleNamespace(history=db, model="htdemucs", label_config=cfg, force_short=False), report)
    assert report.failed == 0
    assert db.get_existing_upload(recent.video_id).youtube_upload_id == "full-upload"
    assert not db.is_short_uploaded(recent.video_id, "htdemucs")


def test_recent_batch_resets_older_backlog_spacing(queue, tmp_path, monkeypatch):
    db, cfg, coordinator = queue
    recent = add_track(db, tmp_path, "NewTrack001", 2)
    other = add_track(db, tmp_path, "NewTrack002", 1)
    context = SimpleNamespace(coordinator=None, priority_request=False, label_config=cfg, history=db)
    sleep = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr("yt_song_to_instrumental.upload_pacing.time.sleep", sleep)
    for track in (recent, other):
        _admit_upload(track, context)
        db.record_upload(track.video_id, "htdemucs", "published-" + track.video_id, "public")
    sleep.assert_not_called()
    older = add_track(db, tmp_path, "OldTrack001", 60)
    with pytest.raises(KeyboardInterrupt):
        _admit_upload(older, context)
    assert 5390 <= sleep.call_args.args[0] <= 9000


@pytest.mark.parametrize("status", ["separation_failed", "render_failed", "upload_failed", "no_thumbnail", "short_failed"])
def test_failed_recent_work_reenters_queue_during_long_paced_run(queue, tmp_path, monkeypatch, status):
    db, _, coordinator = queue
    recent = add_track(db, tmp_path, "NewTrack001", 1)
    old = add_track(db, tmp_path, "OldTrack001", 60)
    if status == "short_failed":
        coordinator.label_config.upload_short = True
        db.record_upload(recent.video_id, "htdemucs", "full-upload", "public")
    clock = Mock(return_value=0)
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.time.monotonic", clock)
    monkeypatch.setattr(coordinator, "refresh", Mock())
    coordinator.attempted.add(recent.video_id)
    coordinator.record_attempt_result(recent.video_id, [TrackReport(recent.video_id, recent.title, recent.artist, status)])
    clock.return_value = 899
    assert coordinator.candidates()[0].video_id == old.video_id
    clock.return_value = 900
    with pytest.raises(UploadDeferred):
        coordinator.before_upload(old)
    assert coordinator.candidates()[0].video_id == recent.video_id
    assert db.get_separation_record(old.video_id, "htdemucs").quality_passed
    if status == "short_failed":
        assert db.get_existing_upload(recent.video_id).youtube_upload_id == "full-upload"


def test_terminal_quality_rejection_is_not_retried_on_cooldown(queue, tmp_path, monkeypatch):
    db, _, coordinator = queue
    track = add_track(db, tmp_path, "NewTrack001", 1)
    coordinator.attempted.add(track.video_id)
    coordinator.record_attempt_result(track.video_id, [TrackReport(track.video_id, track.title, track.artist, "quality_failed")])
    monkeypatch.setattr("yt_song_to_instrumental.source_refresh.time.monotonic", lambda: 10000)
    assert coordinator.candidates() == []
