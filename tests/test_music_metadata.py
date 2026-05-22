from unittest.mock import patch, MagicMock

from yt_song_to_instrumental.music_metadata import (
    lookup_album_index,
    lookup_track,
    lookup_video_date,
    TrackMetadata,
)


class TestLookupTrack:
    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_returns_metadata(self, mock_client):
        mock_client.return_value.get_watch_playlist.return_value = {
            "tracks": [{
                "title": "Driftwood",
                "artists": [
                    {"name": "GLOOMHOUR", "id": "UC1"},
                    {"name": "LIL EMBER", "id": "UC2"},
                ],
                "album": {"name": "Driftwood", "id": "AL1"},
                "videoId": "abc123",
            }]
        }

        result = lookup_track("abc123")

        assert result is not None
        assert result.title == "Driftwood"
        assert result.artists == ["GLOOMHOUR", "LIL EMBER"]
        assert result.album == "Driftwood"

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_returns_none_on_empty_response(self, mock_client):
        mock_client.return_value.get_watch_playlist.return_value = {"tracks": []}

        result = lookup_track("abc123")
        assert result is None

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_returns_none_when_videoid_mismatch(self, mock_client):
        # YTMusic falls back to a related recommendation for non-music videos —
        # we must reject those to avoid misattribution.
        mock_client.return_value.get_watch_playlist.return_value = {
            "tracks": [{
                "title": "Different Song",
                "artists": [{"name": "Other Artist", "id": "UC9"}],
                "album": {"name": "Other Album", "id": "AL9"},
                "videoId": "different_id",
            }]
        }

        result = lookup_track("abc123")
        assert result is None

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_returns_none_on_exception(self, mock_client):
        mock_client.return_value.get_watch_playlist.side_effect = Exception("network error")

        result = lookup_track("abc123")
        assert result is None

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_handles_missing_album(self, mock_client):
        mock_client.return_value.get_watch_playlist.return_value = {
            "tracks": [{
                "title": "Track",
                "artists": [{"name": "Artist", "id": "UC1"}],
                "album": None,
                "videoId": "abc123",
            }]
        }

        result = lookup_track("abc123")
        assert result is not None
        assert result.album == ""


class TestLookupVideoDate:
    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_extracts_publish_date(self, mock_client):
        mock_client.return_value.get_song.return_value = {
            "microformat": {
                "microformatDataRenderer": {
                    "publishDate": "2025-11-13T21:00:45-08:00",
                    "uploadDate": "2025-11-13T21:00:45-08:00",
                }
            }
        }
        assert lookup_video_date("abc") == "20251113"

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_returns_none_on_missing_microformat(self, mock_client):
        mock_client.return_value.get_song.return_value = {}
        assert lookup_video_date("abc") is None

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_returns_none_on_exception(self, mock_client):
        mock_client.return_value.get_song.side_effect = Exception("boom")
        assert lookup_video_date("abc") is None


class TestLookupAlbumIndex:
    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_builds_index_across_albums(self, mock_client):
        client = mock_client.return_value
        client.get_artist.return_value = {
            "albums": {
                "results": [
                    {"title": "Album One", "browseId": "MPRE_one"},
                    {"title": "Album Two", "browseId": "MPRE_two"},
                ],
            },
        }
        client.get_album.side_effect = [
            {"tracks": [{"title": "Track A"}, {"title": "Track B"}]},
            {"tracks": [{"title": "Track C"}]},
        ]
        index = lookup_album_index("UC123")
        assert index == {"track a": "Album One", "track b": "Album One", "track c": "Album Two"}

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_first_album_wins_on_title_collision(self, mock_client):
        client = mock_client.return_value
        client.get_artist.return_value = {
            "albums": {"results": [
                {"title": "Deluxe", "browseId": "MPRE_d"},
                {"title": "Standard", "browseId": "MPRE_s"},
            ]},
        }
        client.get_album.side_effect = [
            {"tracks": [{"title": "Shared"}]},
            {"tracks": [{"title": "Shared"}]},
        ]
        # Deluxe is listed first, so it wins. Documented behaviour.
        assert lookup_album_index("UC123")["shared"] == "Deluxe"

    def test_empty_channel_id_returns_empty(self):
        assert lookup_album_index("") == {}

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_artist_lookup_failure_returns_empty(self, mock_client):
        mock_client.return_value.get_artist.side_effect = Exception("boom")
        assert lookup_album_index("UC123") == {}


class TestResolveMetadata:
    def _info(self, **overrides):
        base = {
            "id": "abc123",
            "title": "yt-dlp Title",
            "webpage_url": "https://youtube.com/watch?v=abc123",
            "uploader": "Some Uploader",
            "channel": "Some Channel",
            "channel_url": "https://youtube.com/c/sc",
        }
        base.update(overrides)
        return base

    def test_ytmusic_wins_for_artist(self):
        from yt_song_to_instrumental.downloader import _resolve_metadata

        info = self._info(uploader="Nyte Vandal", artist=None, album=None)
        ytmusic = TrackMetadata(
            title="velvetine",
            artists=["Nyte Vandal", "Hollow Cair"],
            album="Static Bloom",
        )
        meta = _resolve_metadata(info, ytmusic)

        assert meta["artist"] == "Nyte Vandal, Hollow Cair"
        assert meta["title"] == "velvetine"
        assert meta["album"] == "Static Bloom"
        assert meta["_ytmusic_hit"] is True

    def test_falls_back_to_ytdlp_artist_when_ytmusic_missing(self):
        from yt_song_to_instrumental.downloader import _resolve_metadata

        info = self._info(artist="Riku Vex")
        meta = _resolve_metadata(info, None)

        assert meta["artist"] == "Riku Vex"
        assert meta["_ytmusic_hit"] is False

    def test_falls_back_to_uploader_when_artist_field_missing(self):
        from yt_song_to_instrumental.downloader import _resolve_metadata

        info = self._info(uploader="Nyte Vandal", artist=None)
        meta = _resolve_metadata(info, None)

        assert meta["artist"] == "Nyte Vandal"

    def test_album_chain(self):
        from yt_song_to_instrumental.downloader import _resolve_metadata

        # No YTMusic, no yt-dlp album → empty
        assert _resolve_metadata(self._info(), None)["album"] == ""
        # yt-dlp album present
        assert _resolve_metadata(self._info(album="From YTDLP"), None)["album"] == "From YTDLP"
        # YTMusic wins over yt-dlp
        ytmusic = TrackMetadata(title="t", artists=["a"], album="From YTMusic")
        assert _resolve_metadata(self._info(album="From YTDLP"), ytmusic)["album"] == "From YTMusic"

    def test_title_chain(self):
        from yt_song_to_instrumental.downloader import _resolve_metadata

        # yt-dlp track field wins over yt-dlp title
        info = self._info(track="Clean Track Name")
        assert _resolve_metadata(info, None)["title"] == "Clean Track Name"
        # YTMusic wins over both
        ytmusic = TrackMetadata(title="YTM Title", artists=["a"], album="")
        assert _resolve_metadata(info, ytmusic)["title"] == "YTM Title"
