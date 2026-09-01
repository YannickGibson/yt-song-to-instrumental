from unittest.mock import patch, MagicMock

from yt_song_to_instrumental.music_metadata import (
    album_is_self_titled_single,
    lookup_album_index,
    lookup_track,
    lookup_video_date,
    TrackMetadata,
)


class TestAlbumIsSelfTitledSingle:
    def test_exact_match(self):
        assert album_is_self_titled_single("BOMBA", "BOMBA") is True

    def test_case_insensitive(self):
        assert album_is_self_titled_single("bomba", "BOMBA") is True
        assert album_is_self_titled_single("BOMBA", "bomba") is True

    def test_whitespace_tolerant(self):
        assert album_is_self_titled_single("  BOMBA  ", "BOMBA") is True

    def test_different_strings(self):
        assert album_is_self_titled_single("WHY ALWAYS ME?", "BOMBA") is False

    def test_empty_album(self):
        assert album_is_self_titled_single("", "BOMBA") is False

    def test_empty_title(self):
        assert album_is_self_titled_single("BOMBA", "") is False

    def test_both_empty(self):
        assert album_is_self_titled_single("", "") is False

    def test_feature_parenthetical_in_title(self):
        assert album_is_self_titled_single("All The Same", "All The Same (feat. Zukovstheworld)") is True
        assert album_is_self_titled_single("Platinum", "Platinum (feat. Fimiguerrero)") is True

    def test_feature_in_album_name(self):
        assert album_is_self_titled_single("All The Same (feat. Zukovstheworld)", "All The Same") is True

    def test_solo_and_version_tags(self):
        assert album_is_self_titled_single("Fever (Solo)", "Fever") is True
        assert album_is_self_titled_single("Fever", "Fever (Solo)") is True
        assert album_is_self_titled_single("Trust Issues (Demo Speed)", "Trust Issues") is True

    def test_unparenthesized_features(self):
        assert album_is_self_titled_single("Song Name", "Song Name ft. Other Artist") is True

    def test_single_and_ep_suffixes(self):
        assert album_is_self_titled_single("Song Name - Single", "Song Name") is True

    def test_artist_prefix_in_title(self):
        assert album_is_self_titled_single("Song Name", "Artist - Song Name") is True



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
        assert index.album_for("Track A") == "Album One"
        assert index.album_for("track b") == "Album One"
        assert index.album_for("Track C") == "Album Two"
        # Album One has 2 tracks, Album Two has 1.
        assert index.is_single("Album One") is False
        assert index.is_single("Album Two") is True

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
        assert lookup_album_index("UC123").album_for("shared") == "Deluxe"

    def test_empty_channel_id_returns_empty(self):
        index = lookup_album_index("")
        assert index.album_for("anything") == ""
        assert index.is_single("anything") is False

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_artist_lookup_failure_returns_empty(self, mock_client):
        mock_client.return_value.get_artist.side_effect = Exception("boom")
        assert lookup_album_index("UC123").album_for("anything") == ""

    @patch("yt_song_to_instrumental.music_metadata._get_client")
    def test_is_single_false_for_unknown_album(self, mock_client):
        client = mock_client.return_value
        client.get_artist.return_value = {
            "albums": {"results": [{"title": "Real Album", "browseId": "MPRE_r"}]},
        }
        client.get_album.side_effect = [{"tracks": [{"title": "A"}, {"title": "B"}]}]
        index = lookup_album_index("UC123")
        # An album the index never saw is not assumed to be a single.
        assert index.is_single("Some Unknown Album") is False

    def test_is_single_true_when_album_name_equals_track_title(self):
        # YTMusic files a true single as an "album" named after the song —
        # and singles aren't in the artist's albums section. Name-match
        # catches it with zero extra API cost.
        from yt_song_to_instrumental.music_metadata import AlbumIndex
        index = AlbumIndex({}, {})
        assert index.is_single("BOMBA", "BOMBA") is True
        assert index.is_single("bomba", "BOMBA") is True  # case-insensitive

    def test_is_single_false_when_album_differs_from_title(self):
        from yt_song_to_instrumental.music_metadata import AlbumIndex
        index = AlbumIndex({}, {})
        assert index.is_single("Some Album", "Track Name") is False

    def test_is_single_false_when_album_empty(self):
        from yt_song_to_instrumental.music_metadata import AlbumIndex
        index = AlbumIndex({}, {})
        # No album at all → not a single (there's no album playlist to suppress).
        assert index.is_single("", "Track Name") is False


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
