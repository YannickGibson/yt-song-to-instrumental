import logging
from dataclasses import dataclass

from ytmusicapi import YTMusic

logger = logging.getLogger(__name__)

_ytmusic: YTMusic | None = None


def _get_client() -> YTMusic:
    global _ytmusic
    if _ytmusic is None:
        _ytmusic = YTMusic()
    return _ytmusic


@dataclass
class TrackMetadata:
    title: str
    artists: list[str]
    album: str


def lookup_album_index(channel_id: str) -> dict[str, str]:
    """Build a {track_title_lower: album_name} index for a YT Music artist.

    YTMusic's per-video endpoints (`get_watch_playlist`, `get_song`) return
    `album=None` for artist-channel uploads even when the song is on a known
    album. This index sidesteps that quirk by walking the artist's discography
    once and mapping every album track's title to its album name.
    """
    if not channel_id:
        return {}
    try:
        yt = _get_client()
        artist = yt.get_artist(channel_id)
    except Exception as e:
        logger.warning("YTMusic get_artist failed for %s: %s", channel_id, e)
        return {}
    albums_section = artist.get("albums") or {}
    albums = albums_section.get("results") or []
    browse_id = albums_section.get("browseId")
    if browse_id:
        try:
            albums = yt.get_artist_albums(channel_id, browse_id)
        except Exception as e:
            logger.warning("YTMusic get_artist_albums failed for %s: %s", channel_id, e)

    index: dict[str, str] = {}
    for album_ref in albums:
        album_browse_id = album_ref.get("browseId")
        album_name = album_ref.get("title")
        if not album_browse_id or not album_name:
            continue
        try:
            album_data = yt.get_album(album_browse_id)
        except Exception as e:
            logger.warning("YTMusic get_album failed for %s: %s", album_browse_id, e)
            continue
        for track in album_data.get("tracks") or []:
            title = (track.get("title") or "").strip().lower()
            if title and title not in index:
                index[title] = album_name
    return index


def lookup_video_date(video_id: str) -> str | None:
    """Return the video's publish date in YYYYMMDD form, or None if unavailable.

    Source: YTMusic's get_song microformat. Used by the dry-run preview to show
    upload dates per track (yt-dlp's flat extract doesn't include them for
    music-channel tabs).
    """
    try:
        yt = _get_client()
        song = yt.get_song(video_id)
    except Exception as e:
        logger.warning("YTMusic get_song failed for %s: %s", video_id, e)
        return None
    if not song:
        return None
    iso = (
        song.get("microformat", {})
            .get("microformatDataRenderer", {})
            .get("publishDate")
        or song.get("microformat", {})
            .get("microformatDataRenderer", {})
            .get("uploadDate")
    )
    if not iso or len(iso) < 10:
        return None
    # ISO "2025-11-13T..." → "20251113"
    return iso[0:4] + iso[5:7] + iso[8:10]


def lookup_track(video_id: str) -> TrackMetadata | None:
    try:
        yt = _get_client()
        wp = yt.get_watch_playlist(video_id)
        if not wp or not wp.get("tracks"):
            return None

        track = wp["tracks"][0]
        # YTMusic returns *some* track even for non-music videos — it falls back
        # to a related recommendation. Trust the data only when the videoId
        # matches the one we queried.
        if track.get("videoId") != video_id:
            return None

        artists = [a["name"] for a in track.get("artists", []) if a.get("name")]
        album_info = track.get("album")
        album = album_info["name"] if album_info and album_info.get("name") else ""

        return TrackMetadata(
            title=track.get("title", ""),
            artists=artists,
            album=album,
        )
    except Exception as e:
        logger.warning("YTMusic metadata lookup failed for %s: %s", video_id, e)
        return None
