import logging
import re

from yt_song_to_instrumental.config import LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.metadata import render_playlist_name
from yt_song_to_instrumental.uploader import add_video_to_playlist

logger = logging.getLogger(__name__)

_ARTIST_SPLIT_PATTERN = re.compile(r"\s*(?:,|&|/|\bfeat\.?\s*|\bft\.?\s*|\bx\b)\s*", re.IGNORECASE)
_FEAT_TITLE_PATTERN = re.compile(
    r"\(\s*(?:feat\.?|ft\.?)\s*(.+?)\s*\)", re.IGNORECASE,
)


def split_artists(artist: str) -> list[str]:
    parts = _ARTIST_SPLIT_PATTERN.split(artist)
    return [p.strip() for p in parts if p.strip()]


def extract_featured_artists(title: str) -> list[str]:
    match = _FEAT_TITLE_PATTERN.search(title)
    if not match:
        return []
    return split_artists(match.group(1))


PLAYLIST_TYPE_ARTIST = "artist"
PLAYLIST_TYPE_ALBUM = "album"


def _create_playlist(service, title: str, description: str = "", privacy: str = "public") -> str:
    body = {
        "snippet": {
            "title": title,
            "description": description,
        },
        "status": {
            "privacyStatus": privacy,
        },
    }
    response = service.playlists().insert(part="snippet,status", body=body).execute()
    playlist_id = response["id"]
    logger.info("Created playlist: %s (ID: %s)", title, playlist_id)
    return playlist_id


def _ensure_playlist_privacy(service, playlist_id: str, privacy: str) -> None:
    """Keep an existing playlist's visibility unified with the videos added to
    it: if its privacy differs from `privacy`, update it. No-op when it already
    matches (one cheap playlists.list check)."""
    response = service.playlists().list(part="snippet,status", id=playlist_id).execute()
    items = response.get("items", [])
    if not items:
        return
    current = items[0].get("status", {}).get("privacyStatus")
    if current == privacy:
        return
    snippet = items[0]["snippet"]
    service.playlists().update(
        part="snippet,status",
        body={
            "id": playlist_id,
            "snippet": {
                "title": snippet["title"],
                "description": snippet.get("description", ""),
            },
            "status": {"privacyStatus": privacy},
        },
    ).execute()
    logger.info("Synced playlist %s privacy → %s", playlist_id, privacy)


def get_or_create_artist_playlist(
    service,
    history: HistoryDB,
    label_config: LabelConfig,
    artist: str,
    privacy: str = "public",
) -> str:
    record = history.get_playlist(PLAYLIST_TYPE_ARTIST, artist)
    if record is not None:
        _ensure_playlist_privacy(service, record.youtube_playlist_id, privacy)
        return record.youtube_playlist_id

    title = render_playlist_name(
        label_config.artist_playlist_name_template,
        artist_name=artist,
        label_name=label_config.label_name,
    )
    playlist_id = _create_playlist(service, title, privacy=privacy)
    history.record_playlist(PLAYLIST_TYPE_ARTIST, artist, None, playlist_id)
    return playlist_id


def get_or_create_album_playlist(
    service,
    history: HistoryDB,
    label_config: LabelConfig,
    artist: str,
    album: str,
    privacy: str = "public",
) -> str:
    record = history.get_playlist(PLAYLIST_TYPE_ALBUM, artist, album)
    if record is not None:
        _ensure_playlist_privacy(service, record.youtube_playlist_id, privacy)
        return record.youtube_playlist_id

    title = render_playlist_name(
        label_config.album_playlist_name_template,
        artist_name=artist,
        album_name=album,
        label_name=label_config.label_name,
    )
    playlist_id = _create_playlist(service, title, privacy=privacy)
    history.record_playlist(PLAYLIST_TYPE_ALBUM, artist, album, playlist_id)
    return playlist_id


def project_playlist_artists(
    label_config: LabelConfig,
    artist: str,
    track_title: str,
    primary_artist: str,
) -> list[str]:
    """Resolve which artist playlists a track belongs to.

    The primary artist (the source channel's owner) always gets a playlist —
    that's the reliable fallback. Collaborators get a playlist only when they
    appear in the configured artist_aliases; an unknown guest (e.g. a one-off
    feature) does NOT spawn a playlist. When create_playlists_for_collaborators
    is false, only the primary artist is used.
    """
    resolver = label_config.artist_aliases
    names = [primary_artist]
    if label_config.create_playlists_for_collaborators:
        candidates = split_artists(artist) + extract_featured_artists(track_title)
        names += [c for c in candidates if resolver.is_known(c)]

    seen: set[str] = set()
    resolved_names: list[str] = []
    for name in names:
        resolved = resolver.resolve(name)
        normalized = resolved.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        resolved_names.append(resolved)
    return resolved_names


def project_playlist_names(
    label_config: LabelConfig,
    artist: str,
    album: str,
    track_title: str,
    primary_artist: str,
) -> tuple[list[str], str | None]:
    artist_names = project_playlist_artists(label_config, artist, track_title, primary_artist)
    artist_titles = [
        render_playlist_name(
            label_config.artist_playlist_name_template,
            artist_name=name,
            label_name=label_config.label_name,
        )
        for name in artist_names
    ]
    album_title: str | None = None
    if album:
        # Album playlist is credited to the primary (channel) artist, resolved
        # through aliases — matching the rendered video-title convention.
        album_artist = label_config.artist_aliases.resolve(primary_artist)
        album_title = render_playlist_name(
            label_config.album_playlist_name_template,
            artist_name=album_artist,
            album_name=album,
            label_name=label_config.label_name,
        )
    return artist_titles, album_title


def assign_to_playlists(
    service,
    history: HistoryDB,
    label_config: LabelConfig,
    video_id: str,
    artist: str,
    album: str,
    primary_artist: str,
    privacy: str = "public",
    track_title: str = "",
) -> None:
    for resolved in project_playlist_artists(label_config, artist, track_title, primary_artist):
        artist_playlist_id = get_or_create_artist_playlist(
            service, history, label_config, resolved, privacy,
        )
        add_video_to_playlist(service, artist_playlist_id, video_id)

    if album:
        album_artist = label_config.artist_aliases.resolve(primary_artist)
        album_playlist_id = get_or_create_album_playlist(
            service, history, label_config, album_artist, album, privacy,
        )
        add_video_to_playlist(service, album_playlist_id, video_id)
