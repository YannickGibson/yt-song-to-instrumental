import logging
import re
from dataclasses import dataclass

from ytmusicapi import YTMusic

logger = logging.getLogger(__name__)

_ytmusic: YTMusic | None = None

_SINGLE_NOISE_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")
_UNPAREN_FEAT_RE = re.compile(r"^(.+?)\s+(?:ft|feat)\.?\s+(.+)$", re.IGNORECASE)
_DASH_SPLIT_RE = re.compile(r"\s+[\-–—]\s+")
_SINGLE_SUFFIX_RE = re.compile(r"\s*[\-–—]\s*(?:single|ep|speed|demo|sped\s+up|slowed)\s*$", re.IGNORECASE)


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


@dataclass
class AlbumIndex:
    """An artist's discography mapped two ways: track title → album name, and
    album name → track count. The track count lets callers suppress album
    playlists for single-track releases (a 'single' isn't an album)."""
    title_to_album: dict[str, str]
    album_sizes: dict[str, int]

    def album_for(self, title: str) -> str:
        return self.title_to_album.get(title.strip().lower(), "")

    def is_single(self, album_name: str, track_title: str = "") -> bool:
        """True when the album is a single-track release. Two signals:

        1. The album appears in this index with track count <= 1.
        2. The album name corresponds to the track title (see album_is_self_titled_single).
        """
        album_key = (album_name or "").strip().lower()
        size = self.album_sizes.get(album_key)
        if size is not None:
            return size <= 1
        return album_is_self_titled_single(album_name, track_title)


def _normalize_title_or_album(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    # Strip parentheticals like (feat. X), (Solo), (Demo Speed), (Sped Up), etc.
    t = _SINGLE_NOISE_PARENS_RE.sub(" ", t).strip()
    # Strip unparenthesized features: "Song ft. X" -> "Song"
    m = _UNPAREN_FEAT_RE.match(t)
    if m:
        t = m.group(1).strip()
    # Strip trailing " - Single", " - EP", etc.
    t = _SINGLE_SUFFIX_RE.sub("", t).strip()
    # If there is an artist delimiter dash (e.g. "Artist - Song"), use the song name
    parts = _DASH_SPLIT_RE.split(t)
    if len(parts) == 2:
        t = parts[1].strip()
    return re.sub(r"[^a-zA-Z0-9]", "", t).lower()


def album_is_self_titled_single(album_name: str, track_title: str) -> bool:
    """True when the album name corresponds to the single track title (accounting
    for feature credits, parenthetical tags like '(feat. X)', '(Solo)',
    '(Demo Speed)', and trailing suffixes like '- Single').

    Used both by AlbumIndex.is_single (preview path) and assign_to_playlists
    (upload path) to suppress an album-playlist creation for singles.
    """
    if not album_name or not track_title:
        return False
    norm_album = _normalize_title_or_album(album_name)
    norm_track = _normalize_title_or_album(track_title)
    return bool(norm_album) and norm_album == norm_track


def lookup_album_index(channel_id: str) -> AlbumIndex:
    """Build an AlbumIndex for a YT Music artist.

    YTMusic's per-video endpoints (`get_watch_playlist`, `get_song`) return
    `album=None` for artist-channel uploads even when the song is on a known
    album. This index sidesteps that quirk by walking the artist's discography
    once.
    """
    empty = AlbumIndex({}, {})
    if not channel_id:
        return empty
    try:
        yt = _get_client()
        artist = yt.get_artist(channel_id)
    except Exception as e:
        logger.warning("YTMusic get_artist failed for %s: %s", channel_id, e)
        return empty
    albums_section = artist.get("albums") or {}
    albums = albums_section.get("results") or []
    browse_id = albums_section.get("browseId")
    if browse_id:
        try:
            albums = yt.get_artist_albums(channel_id, browse_id)
        except Exception as e:
            logger.warning("YTMusic get_artist_albums failed for %s: %s", channel_id, e)

    title_to_album: dict[str, str] = {}
    album_sizes: dict[str, int] = {}
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
        tracks = album_data.get("tracks") or []
        album_sizes[album_name.strip().lower()] = len(tracks)
        for track in tracks:
            title = (track.get("title") or "").strip().lower()
            if title and title not in title_to_album:
                title_to_album[title] = album_name
    return AlbumIndex(title_to_album, album_sizes)


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
