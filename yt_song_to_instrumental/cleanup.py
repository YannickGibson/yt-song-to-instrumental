import logging
import re
from dataclasses import dataclass
from pathlib import Path

from yt_song_to_instrumental.constants import SHORT_ALTERNATE_SOURCE_MARKER

logger = logging.getLogger(__name__)

# YouTube video IDs are exactly 11 chars from [A-Za-z0-9_-]. The orphan sweep
# uses this to identify candidate artifact files from arbitrary filenames.
_VIDEO_ID_RE = re.compile(r"^([A-Za-z0-9_-]{11})(?:\.|_)")
_SOURCE_VIDEO_ID_RE = re.compile(r"^video_([A-Za-z0-9_-]{11})(?:\.|_)")


def _artifact_video_id(path: Path) -> str | None:
    """Return the owning YouTube ID for a recognized artifact filename."""
    match = _SOURCE_VIDEO_ID_RE.match(path.name) or _VIDEO_ID_RE.match(path.name)
    return match.group(1) if match else None


@dataclass
class CleanupResult:
    removed_files: list[Path]
    bytes_freed: int


def cleanup_track_artifacts(
    video_id: str,
    model: str,
    tmp_dir: Path,
    output_dir: Path,
) -> CleanupResult:
    """Delete on-disk artifacts for a track that has been uploaded successfully.

    Removes (when present):
      - tmp/<video_id>.* (raw audio download + thumbnail in any extension)
      - tmp/video_<video_id>.* (source video downloaded for a Short)
      - tmp/video_<video_id>_alternate.* (verified alternate music video)
      - <output_dir>/<model>/<model>/<video_id>/*.wav (separated stems)
      - <output_dir>/<model>/<video_id>_instrumental.mp4 (rendered upload video)

    Idempotent: missing files are silently skipped, missing directories ignored.
    Empty stem directories are removed after their contents are deleted.

    The double `<model>/<model>` nesting is real: separator backends scope their
    output under their own model name inside the caller-passed model dir.
    """
    candidates: list[Path] = []
    candidates.extend(p for p in tmp_dir.glob(f"{video_id}.*") if p.is_file())
    candidates.extend(p for p in tmp_dir.glob(f"video_{video_id}.*") if p.is_file())
    candidates.extend(
        p
        for p in tmp_dir.glob(
            f"video_{video_id}{SHORT_ALTERNATE_SOURCE_MARKER}.*"
        )
        if p.is_file()
    )

    model_dir = output_dir / model
    stem_dir = model_dir / model / video_id
    if stem_dir.is_dir():
        candidates.extend(p for p in stem_dir.iterdir() if p.is_file())

    rendered_video = model_dir / f"{video_id}_instrumental.mp4"
    if rendered_video.is_file():
        candidates.append(rendered_video)

    short_video = model_dir / f"{video_id}_short.mp4"
    if short_video.is_file():
        candidates.append(short_video)

    removed: list[Path] = []
    freed = 0
    for p in candidates:
        try:
            size = p.stat().st_size
            p.unlink()
            removed.append(p)
            freed += size
        except OSError as e:
            logger.warning("Failed to delete %s: %s", p, e)

    if stem_dir.is_dir():
        try:
            stem_dir.rmdir()  # only succeeds when empty — leaves non-empty dirs alone
        except OSError:
            pass

    if removed:
        logger.info(
            "Cleanup %s: removed %d files (%.1f MB)",
            video_id, len(removed), freed / (1024 * 1024),
        )
    return CleanupResult(removed_files=removed, bytes_freed=freed)


def cleanup_all_uploaded(
    history,
    tmp_dir: Path,
    output_dir: Path,
) -> CleanupResult:
    """Run cleanup for every (video_id, model) pair that has a row in `uploads`.
    Returns the aggregated result across all sweeps."""
    total_files: list[Path] = []
    total_bytes = 0
    seen: set[tuple[str, str]] = set()
    for record in history.get_all_uploads():
        key = (record.video_id, record.model)
        if key in seen:
            continue
        seen.add(key)
        result = cleanup_track_artifacts(record.video_id, record.model, tmp_dir, output_dir)
        total_files.extend(result.removed_files)
        total_bytes += result.bytes_freed
    return CleanupResult(removed_files=total_files, bytes_freed=total_bytes)


def cleanup_orphan_artifacts(
    history,
    tmp_dir: Path,
    output_dir: Path,
) -> CleanupResult:
    """Sweep on-disk artifacts whose video_id no longer has any row in
    `downloads`. These are leftovers from prior runs whose history was deleted
    (e.g. a duplicate cleanup) — the per-upload sweep can't find them because
    nothing in the DB points at them.

    Only removes files matching the project's own artifact naming patterns,
    never arbitrary files. Preserves anything whose video_id is still tracked,
    even if it isn't uploaded yet (could be mid-pipeline).
    """
    known_ids: set[str] = {d.video_id for d in history.get_all_downloads()}

    candidates: list[Path] = []

    if tmp_dir.is_dir():
        for path in tmp_dir.iterdir():
            if not path.is_file():
                continue
            video_id = _artifact_video_id(path)
            if video_id and video_id not in known_ids:
                candidates.append(path)

    if output_dir.is_dir():
        for path in output_dir.rglob("*"):
            if not path.is_file():
                continue
            video_id = _artifact_video_id(path)
            if video_id and video_id not in known_ids:
                candidates.append(path)
            elif path.parent.name and len(path.parent.name) == 11:
                # Stem files (vocals.wav, no_vocals.wav) sit under <video_id>/.
                if _VIDEO_ID_RE.match(path.parent.name + "."):
                    if path.parent.name not in known_ids:
                        candidates.append(path)

    removed: list[Path] = []
    freed = 0
    for p in candidates:
        try:
            size = p.stat().st_size
            p.unlink()
            removed.append(p)
            freed += size
        except OSError as e:
            logger.warning("Failed to delete orphan %s: %s", p, e)

    # Try to remove now-empty <video_id> stem dirs.
    if output_dir.is_dir():
        for path in sorted(output_dir.rglob("*"), key=lambda p: -len(p.parts)):
            if path.is_dir() and len(path.name) == 11 and _VIDEO_ID_RE.match(path.name + "."):
                try:
                    path.rmdir()
                except OSError:
                    pass

    if removed:
        logger.info(
            "Orphan cleanup: removed %d files (%.1f MB)",
            len(removed), freed / (1024 * 1024),
        )
    return CleanupResult(removed_files=removed, bytes_freed=freed)
