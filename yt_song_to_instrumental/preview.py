import logging
from dataclasses import dataclass, field

from yt_song_to_instrumental.config import LabelConfig
from yt_song_to_instrumental.constants import DEFAULT_MODEL, MODEL_DISPLAY_NAMES
from yt_song_to_instrumental.downloader import (
    dedupe_entries_prefer_audio,
    enumerate_videos,
    fetch_preview_metadata,
)
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.metadata import render_video_title
from yt_song_to_instrumental.music_metadata import lookup_album_index
from yt_song_to_instrumental.playlists import project_playlist_names

logger = logging.getLogger(__name__)


@dataclass
class PreviewTrack:
    video_id: str
    url: str
    title: str
    artist: str
    album: str
    enriched: bool
    already_downloaded: bool
    projected_artist_playlists: list[str]
    projected_album_playlist: str | None
    projected_video_title: str
    upload_date: str | None  # YYYYMMDD as yt-dlp returns it, or None if unknown


@dataclass
class PreviewReport:
    source_url: str
    after_date: str | None
    total_seen: int = 0
    new_videos: list[PreviewTrack] = field(default_factory=list)
    skipped_existing: int = 0
    duplicates_dropped: int = 0
    filtered_by_date: int = 0
    artist_playlist_totals: dict[str, int] = field(default_factory=dict)
    album_playlist_totals: dict[str, int] = field(default_factory=dict)
    enumeration_failed: bool = False


def _entry_url(entry: dict) -> str:
    return entry.get("url") or entry.get("webpage_url") or ""


def _flat_fallback_title(entry: dict) -> str:
    return entry.get("title") or "Unknown"


def _flat_fallback_uploader(entry: dict) -> str:
    return entry.get("uploader") or entry.get("channel") or "Unknown"


def preview_url(
    url: str,
    label_config: LabelConfig,
    history: HistoryDB,
    after_date: str | None = None,
    model_name: str = DEFAULT_MODEL,
) -> PreviewReport:
    report = PreviewReport(source_url=url, after_date=after_date)
    model_display = MODEL_DISPLAY_NAMES.get(model_name, model_name)

    entries = enumerate_videos(url, after_date=after_date)
    if not entries:
        report.enumeration_failed = True
        return report

    report.total_seen = len(entries)
    entries = dedupe_entries_prefer_audio(entries)
    report.duplicates_dropped = report.total_seen - len(entries)

    # Build the per-artist album-name index once. Used to backfill album info
    # for tracks where YTMusic's per-video endpoints return album=None (a
    # known data quirk for artist-channel uploads).
    source_channel_id = ""
    for e in entries:
        if e.get("_source_channel_id"):
            source_channel_id = e["_source_channel_id"]
            break
    album_index = lookup_album_index(source_channel_id) if source_channel_id else {}

    for entry in entries:
        video_id = entry.get("id") or ""
        if not video_id:
            continue

        if history.is_downloaded(video_id):
            report.skipped_existing += 1
            continue

        meta = fetch_preview_metadata(
            video_id,
            fallback_title=_flat_fallback_title(entry),
            fallback_uploader=_flat_fallback_uploader(entry),
        )

        track_date = entry.get("upload_date") or meta.get("_upload_date")
        if after_date and track_date and track_date < after_date:
            report.filtered_by_date += 1
            continue

        if not meta["album"] and album_index:
            meta["album"] = album_index.get(meta["title"].strip().lower(), "")

        primary_artist = (
            entry.get("_source_channel")
            or entry.get("uploader")
            or entry.get("channel")
            or meta["artist"]
            or "Unknown"
        )
        artist_playlists, album_playlist = project_playlist_names(
            label_config, meta["artist"], meta["album"], meta["title"], primary_artist,
        )
        projected_video_title = render_video_title(
            label_config.video_title_template,
            primary_artist=primary_artist,
            raw_title=meta["title"],
            all_artists=meta.get("_all_artists") or [meta["artist"]],
            album_name=meta["album"],
            model_name=model_display,
            label_name=label_config.label_name,
            aliases=label_config.artist_aliases,
        )

        report.new_videos.append(PreviewTrack(
            video_id=video_id,
            url=_entry_url(entry),
            title=meta["title"],
            artist=meta["artist"],
            album=meta["album"],
            enriched=bool(meta["_ytmusic_hit"]),
            already_downloaded=False,
            projected_artist_playlists=artist_playlists,
            projected_album_playlist=album_playlist,
            projected_video_title=projected_video_title,
            upload_date=entry.get("upload_date") or meta.get("_upload_date"),
        ))

        for name in artist_playlists:
            report.artist_playlist_totals[name] = report.artist_playlist_totals.get(name, 0) + 1
        if album_playlist:
            report.album_playlist_totals[album_playlist] = (
                report.album_playlist_totals.get(album_playlist, 0) + 1
            )

    return report
