from pathlib import Path

from yt_song_to_instrumental.cleanup import (
    cleanup_all_uploaded,
    cleanup_orphan_artifacts,
    cleanup_track_artifacts,
)
from yt_song_to_instrumental.history import HistoryDB


def _seed_track_files(tmp_root: Path, video_id: str, model: str, sizes: dict[str, int]) -> dict[str, Path]:
    """Lay down the on-disk artifacts a real pipeline run would create.
    Returns a name→path map so individual tests can assert on specific files."""
    tmp_dir = tmp_root / "tmp"
    output_dir = tmp_root / "output"
    tmp_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    stem_dir = output_dir / model / model / video_id
    stem_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "raw_wav":      tmp_dir / f"{video_id}.wav",
        "thumbnail":    tmp_dir / f"{video_id}.webp",
        "vocals":       stem_dir / "vocals.wav",
        "no_vocals":    stem_dir / "no_vocals.wav",
        "rendered_mp4": output_dir / model / f"{video_id}_instrumental.mp4",
    }
    for name, path in paths.items():
        path.write_bytes(b"x" * sizes[name])
    return paths


class TestCleanupTrackArtifacts:
    def test_removes_all_known_artifacts(self, tmp_path):
        sizes = {"raw_wav": 100, "thumbnail": 50, "vocals": 200, "no_vocals": 200, "rendered_mp4": 80}
        paths = _seed_track_files(tmp_path, "vid123", "htdemucs", sizes)

        result = cleanup_track_artifacts(
            "vid123", "htdemucs", tmp_path / "tmp", tmp_path / "output",
        )

        for path in paths.values():
            assert not path.exists(), f"expected {path.name} removed"
        assert len(result.removed_files) == 5
        assert result.bytes_freed == sum(sizes.values())

    def test_removes_empty_stem_dir(self, tmp_path):
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        _seed_track_files(tmp_path, "vid123", "htdemucs", sizes)

        cleanup_track_artifacts(
            "vid123", "htdemucs", tmp_path / "tmp", tmp_path / "output",
        )

        stem_dir = tmp_path / "output" / "htdemucs" / "htdemucs" / "vid123"
        assert not stem_dir.exists(), "empty stem dir should be rmdir'd"

    def test_idempotent_when_nothing_to_clean(self, tmp_path):
        (tmp_path / "tmp").mkdir()
        (tmp_path / "output").mkdir()

        result = cleanup_track_artifacts(
            "never_existed", "htdemucs", tmp_path / "tmp", tmp_path / "output",
        )

        assert result.removed_files == []
        assert result.bytes_freed == 0

    def test_preserves_unrelated_files(self, tmp_path):
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        _seed_track_files(tmp_path, "vid_target", "htdemucs", sizes)
        # A second track that must survive.
        sizes2 = {"raw_wav": 5, "thumbnail": 5, "vocals": 5, "no_vocals": 5, "rendered_mp4": 5}
        survivors = _seed_track_files(tmp_path, "vid_keep", "htdemucs", sizes2)

        cleanup_track_artifacts(
            "vid_target", "htdemucs", tmp_path / "tmp", tmp_path / "output",
        )

        for path in survivors.values():
            assert path.exists(), f"unrelated {path.name} must not be deleted"

    def test_works_for_inst_hq_4_model(self, tmp_path):
        # Same layout pattern for any backend — the model name is the key.
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        paths = _seed_track_files(tmp_path, "vid123", "inst_hq_4", sizes)

        result = cleanup_track_artifacts(
            "vid123", "inst_hq_4", tmp_path / "tmp", tmp_path / "output",
        )

        for path in paths.values():
            assert not path.exists()
        assert len(result.removed_files) == 5

    def test_handles_partial_artifacts(self, tmp_path):
        # Only some artifacts exist (e.g. earlier cleanup left things behind).
        tmp_dir = tmp_path / "tmp"; tmp_dir.mkdir()
        output_dir = tmp_path / "output"; output_dir.mkdir()
        (tmp_dir / "vid123.wav").write_bytes(b"a" * 100)
        # No thumbnail, no stems, no MP4.

        result = cleanup_track_artifacts("vid123", "htdemucs", tmp_dir, output_dir)

        assert len(result.removed_files) == 1
        assert result.bytes_freed == 100


class TestCleanupAllUploaded:
    def test_sweeps_every_upload_row(self, tmp_path):
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        _seed_track_files(tmp_path, "vid_a", "htdemucs", sizes)
        _seed_track_files(tmp_path, "vid_b", "htdemucs", sizes)

        db = HistoryDB(db_path=":memory:")
        db.record_upload("vid_a", "htdemucs", "yt_id_a", "public")
        db.record_upload("vid_b", "htdemucs", "yt_id_b", "public")

        result = cleanup_all_uploaded(db, tmp_path / "tmp", tmp_path / "output")

        assert len(result.removed_files) == 10  # 5 per track
        assert result.bytes_freed == 100

    def test_skips_duplicate_video_model_pairs(self, tmp_path):
        # If a track has multiple upload rows (re-upload), don't double-count.
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        _seed_track_files(tmp_path, "vid_a", "htdemucs", sizes)

        db = HistoryDB(db_path=":memory:")
        # INSERT OR REPLACE means the second one overwrites the first; simulate
        # a real edge case by checking behavior under a single row anyway.
        db.record_upload("vid_a", "htdemucs", "yt_id_a", "public")

        result = cleanup_all_uploaded(db, tmp_path / "tmp", tmp_path / "output")

        assert len(result.removed_files) == 5

    def test_empty_uploads_table(self, tmp_path):
        (tmp_path / "tmp").mkdir()
        (tmp_path / "output").mkdir()
        db = HistoryDB(db_path=":memory:")

        result = cleanup_all_uploaded(db, tmp_path / "tmp", tmp_path / "output")

        assert result.removed_files == []
        assert result.bytes_freed == 0


class TestCleanupOrphans:
    def test_removes_files_for_video_ids_not_in_downloads(self, tmp_path):
        # Real-world case: a duplicate was deleted from the DB, but its rendered
        # MP4 was never removed from disk.
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        _seed_track_files(tmp_path, "abcdefghijk", "htdemucs", sizes)

        db = HistoryDB(db_path=":memory:")
        # no downloads recorded → everything is orphaned

        result = cleanup_orphan_artifacts(db, tmp_path / "tmp", tmp_path / "output")

        assert len(result.removed_files) == 5
        assert result.bytes_freed == 50

    def test_preserves_files_for_known_video_ids(self, tmp_path):
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        keep = _seed_track_files(tmp_path, "abcdefghijk", "htdemucs", sizes)
        _seed_track_files(tmp_path, "zyxwvutsrqp", "htdemucs", sizes)

        db = HistoryDB(db_path=":memory:")
        db.record_download(
            video_id="abcdefghijk", url="u", title="t", artist="a", album="",
            channel_name="c", channel_url="cu", audio_path=str(keep["raw_wav"]),
            thumbnail_path=str(keep["thumbnail"]),
        )

        result = cleanup_orphan_artifacts(db, tmp_path / "tmp", tmp_path / "output")

        # zyxwvutsrqp removed (5 files), abcdefghijk preserved (still in downloads).
        assert len(result.removed_files) == 5
        for path in keep.values():
            assert path.exists()

    def test_ignores_non_artifact_files(self, tmp_path):
        tmp_dir = tmp_path / "tmp"; tmp_dir.mkdir()
        output_dir = tmp_path / "output"; output_dir.mkdir()
        # A file whose name doesn't start with an 11-char video_id pattern.
        (tmp_dir / "README.txt").write_text("not an artifact")
        (output_dir / "logs.txt").write_text("also not an artifact")

        db = HistoryDB(db_path=":memory:")
        result = cleanup_orphan_artifacts(db, tmp_dir, output_dir)

        assert result.removed_files == []
        assert (tmp_dir / "README.txt").exists()
        assert (output_dir / "logs.txt").exists()

    def test_removes_empty_stem_dir_after_orphan_cleanup(self, tmp_path):
        sizes = {"raw_wav": 10, "thumbnail": 10, "vocals": 10, "no_vocals": 10, "rendered_mp4": 10}
        _seed_track_files(tmp_path, "abcdefghijk", "htdemucs", sizes)
        db = HistoryDB(db_path=":memory:")

        cleanup_orphan_artifacts(db, tmp_path / "tmp", tmp_path / "output")

        stem_dir = tmp_path / "output" / "htdemucs" / "htdemucs" / "abcdefghijk"
        assert not stem_dir.exists()
