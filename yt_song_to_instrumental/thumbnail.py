import logging
import urllib.request
from pathlib import Path

from yt_song_to_instrumental.constants import THUMBNAIL_RESOLUTION_ORDER

logger = logging.getLogger(__name__)


def fetch_thumbnail(video_id: str, output_dir: Path) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for res in THUMBNAIL_RESOLUTION_ORDER:
        url = f"https://img.youtube.com/vi/{video_id}/{res}.jpg"
        output_path = output_dir / f"{video_id}_thumb.jpg"
        try:
            urllib.request.urlretrieve(url, output_path)
            if output_path.exists() and output_path.stat().st_size > 1000:
                logger.info("Fetched thumbnail at %s resolution", res)
                return output_path
        except (urllib.error.URLError, OSError) as e:
            logger.debug("Failed to fetch %s thumbnail: %s", res, e)
            continue

    logger.warning("Could not fetch any thumbnail for %s", video_id)
    return None


def get_thumbnail_for_track(
    video_id: str,
    existing_thumbnail: Path,
    tmp_dir: Path,
) -> Path | None:
    if existing_thumbnail and existing_thumbnail.exists() and existing_thumbnail.stat().st_size > 0:
        return existing_thumbnail
    return fetch_thumbnail(video_id, tmp_dir)
