from unittest.mock import patch

from yt_song_to_instrumental.config import LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.preview import preview_url


def _make_label_config(
    create_playlists_for_collaborators: bool = True,
    aliases: list[list[str]] | None = None,
) -> LabelConfig:
    data = {
        "channel": {"name": "Test", "description": "T"},
        "label": {"name": "TestLabel"},
        "templates": {
            "video_title": "<artist-name>",
            "video_description": "D",
            "album_playlist_name": "<artist-name> — <album-name> Instrumentals",
            "artist_playlist_name": "<artist-name> Instrumentals",
        },
        "create_playlists_for_collaborators": create_playlists_for_collaborators,
        "sources": [],
    }
    if aliases is not None:
        data["artist_aliases"] = aliases
    return LabelConfig(data)


def _entry(vid: str, title: str | None = None, source_channel: str | None = None) -> dict:
    entry = {
        "id": vid,
        # Default title unique-per-vid so dedup doesn't collapse fixture entries.
        "title": title if title is not None else f"track-{vid}",
        "webpage_url": f"https://yt.com/watch?v={vid}",
        "url": f"https://yt.com/watch?v={vid}",
    }
    if source_channel is not None:
        entry["_source_channel"] = source_channel
    return entry


def _meta(
    vid: str,
    artist: str = "Artist",
    album: str = "",
    title: str = "Track",
    ytmusic_hit: bool = True,
    upload_date: str | None = None,
) -> dict:
    return {
        "video_id": vid,
        "url": f"https://yt.com/watch?v={vid}",
        "title": title,
        "artist": artist,
        "album": album,
        "channel_name": "ch",
        "channel_url": "https://yt.com/c",
        "_ytmusic_hit": ytmusic_hit,
        "_upload_date": upload_date,
    }


class TestPreviewUrl:
    def test_enumeration_failure_marks_report(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[]):
            report = preview_url("https://yt.com/bad", cfg, db)
        assert report.enumeration_failed is True
        assert report.new_videos == []

    def test_already_downloaded_is_skipped(self):
        db = HistoryDB(":memory:")
        db.record_download(
            video_id="a", url="u", title="T", artist="A", album="",
            channel_name="c", channel_url="cu", audio_path="p", thumbnail_path="tp",
        )
        cfg = _make_label_config()
        entries = [_entry("a"), _entry("b")]
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=entries), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata", return_value=_meta("b", "Nyte Vandal")):
            report = preview_url("https://yt.com/x", cfg, db)
        assert report.total_seen == 2
        assert report.skipped_existing == 1
        assert len(report.new_videos) == 1
        assert report.new_videos[0].video_id == "b"

    def test_known_collaborator_projected_unknown_dropped(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config(
            create_playlists_for_collaborators=True,
            aliases=[["Nyte Vandal"], ["Hollow Cair"]],
        )
        entry = _entry("a", source_channel="Nyte Vandal")
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[entry]), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a", artist="Nyte Vandal, Hollow Cair, Some Guest", title="Track")):
            report = preview_url("https://yt.com/x", cfg, db)
        # Known artists get playlists; "Some Guest" (not in aliases) is dropped.
        assert report.new_videos[0].projected_artist_playlists == [
            "Nyte Vandal Instrumentals",
            "Hollow Cair Instrumentals",
        ]

    def test_unknown_collaborators_fall_back_to_channel(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config(create_playlists_for_collaborators=True)  # no aliases
        entry = _entry("a", source_channel="fauxpelt")
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[entry]), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a", artist="fauxpelt archive, Dj Quartz", title="afterglow")):
            report = preview_url("https://yt.com/x", cfg, db)
        # No collaborator is alias-known → only the channel's primary artist.
        assert report.new_videos[0].projected_artist_playlists == ["fauxpelt Instrumentals"]
        assert report.artist_playlist_totals == {"fauxpelt Instrumentals": 1}

    def test_projected_video_title_uses_template(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[_entry("a")]), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a", artist="Nyte Vandal", title="velvetine")):
            report = preview_url("https://yt.com/x", cfg, db)
        # _make_label_config uses video_title template "<artist-name>"
        assert report.new_videos[0].projected_video_title == "Nyte Vandal"

    def test_features_off_uses_primary_only(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config(
            create_playlists_for_collaborators=False,
            aliases=[["Hollow Cair"]],
        )
        entry = _entry("a", source_channel="Nyte Vandal")
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[entry]), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a", artist="Nyte Vandal, Hollow Cair", title="Track (feat. Hollow Cair)")):
            report = preview_url("https://yt.com/x", cfg, db)
        # Flag off → only the channel's primary artist, even though Destroy
        # Lonely is alias-known.
        assert report.new_videos[0].projected_artist_playlists == ["Nyte Vandal Instrumentals"]
        assert report.artist_playlist_totals == {"Nyte Vandal Instrumentals": 1}

    def test_album_playlist_totals(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        with patch("yt_song_to_instrumental.preview.enumerate_videos",
                   return_value=[_entry("a"), _entry("b")]), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   side_effect=[
                       _meta("a", artist="Riku Vex", album="Quiet Hours"),
                       _meta("b", artist="Riku Vex", album="Quiet Hours"),
                   ]):
            report = preview_url("https://yt.com/x", cfg, db)
        assert report.album_playlist_totals == {
            "Riku Vex — Quiet Hours Instrumentals": 2,
        }

    def test_album_index_backfills_missing_album(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        entry = _entry("a", title="Static Crown")
        entry["_source_channel_id"] = "UC123"
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[entry]), \
             patch("yt_song_to_instrumental.preview.lookup_album_index",
                   return_value={"static crown": "Static Bloom"}), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a", artist="Nyte Vandal", album="", title="Static Crown")):
            report = preview_url("https://yt.com/x", cfg, db)
        assert report.new_videos[0].album == "Static Bloom"
        # And it shows up as a projected album playlist.
        assert "Nyte Vandal — Static Bloom Instrumentals" in report.album_playlist_totals

    def test_album_index_does_not_overwrite_ytmusic_album(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        entry = _entry("a", title="Track")
        entry["_source_channel_id"] = "UC123"
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[entry]), \
             patch("yt_song_to_instrumental.preview.lookup_album_index",
                   return_value={"track": "Index Album"}), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a", album="Direct Album")):
            report = preview_url("https://yt.com/x", cfg, db)
        assert report.new_videos[0].album == "Direct Album"

    def test_after_date_filter_uses_ytmusic_date(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        entries = [_entry("new"), _entry("old")]
        metas = {
            "new": _meta("new", title="New", upload_date="20250601"),
            "old": _meta("old", title="Old", upload_date="20230101"),
        }
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=entries), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   side_effect=lambda vid, **_: metas[vid]):
            report = preview_url("https://yt.com/x", cfg, db, after_date="20240101")
        assert report.filtered_by_date == 1
        assert len(report.new_videos) == 1
        assert report.new_videos[0].video_id == "new"

    def test_after_date_filter_keeps_unknown_dates(self):
        # YTMusic missed the date — be permissive rather than silently dropping.
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        entries = [_entry("x")]
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=entries), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("x", upload_date=None)):
            report = preview_url("https://yt.com/x", cfg, db, after_date="20240101")
        assert report.filtered_by_date == 0
        assert len(report.new_videos) == 1

    def test_duplicates_dropped_count_reported(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        # Two entries with the same parens-stripped title; dedup keeps the audio.
        entries = [
            _entry("v1", title="Static Crown (Official Music Video)"),
            _entry("a1", title="Static Crown (Audio)"),
        ]
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=entries), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata",
                   return_value=_meta("a1", artist="Nyte Vandal", title="Static Crown")):
            report = preview_url("https://yt.com/x", cfg, db)
        assert report.total_seen == 2
        assert report.duplicates_dropped == 1
        assert len(report.new_videos) == 1
        assert report.new_videos[0].video_id == "a1"

    def test_unenriched_track_marked(self):
        db = HistoryDB(":memory:")
        cfg = _make_label_config()
        # YTMusic missed: fetch_preview_metadata returns flat-entry fallbacks
        # with _ytmusic_hit=False.
        miss = {
            "video_id": "a",
            "title": "Some Title",
            "artist": "Some Uploader",
            "album": "",
            "_ytmusic_hit": False,
        }
        with patch("yt_song_to_instrumental.preview.enumerate_videos", return_value=[_entry("a", title="Some Title")]), \
             patch("yt_song_to_instrumental.preview.fetch_preview_metadata", return_value=miss):
            report = preview_url("https://yt.com/x", cfg, db)
        assert len(report.new_videos) == 1
        assert report.new_videos[0].enriched is False
        assert report.new_videos[0].title == "Some Title"
