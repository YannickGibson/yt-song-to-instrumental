from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_song_to_instrumental.downloader import (
    DownloadedTrack,
    _find_thumbnail,
    dedupe_entries_prefer_audio,
    download_tracks,
    enumerate_videos,
)
from yt_song_to_instrumental.history import HistoryDB


def _make_info(video_id: str = "abc123", title: str = "Test Song") -> dict:
    return {
        "id": video_id,
        "title": title,
        "webpage_url": f"https://youtube.com/watch?v={video_id}",
        "artist": "Test Artist",
        "album": "Test Album",
        "channel": "Test Channel",
        "channel_url": "https://youtube.com/c/testchannel",
        "thumbnails": [{"url": "https://img.youtube.com/maxres.jpg", "preference": 10}],
    }


class TestFindThumbnail:
    def test_finds_jpg(self, tmp_path):
        (tmp_path / "abc123.jpg").touch()
        result = _find_thumbnail(tmp_path, "abc123")
        assert result == tmp_path / "abc123.jpg"

    def test_finds_webp(self, tmp_path):
        (tmp_path / "abc123.webp").touch()
        result = _find_thumbnail(tmp_path, "abc123")
        assert result == tmp_path / "abc123.webp"

    def test_returns_empty_path_when_missing(self, tmp_path):
        result = _find_thumbnail(tmp_path, "abc123")
        assert result == Path("")


class TestEnumerateVideos:
    def _ydl_returning(self, *infos):
        instances = []
        for info in infos:
            inst = MagicMock()
            inst.__enter__ = MagicMock(return_value=inst)
            inst.__exit__ = MagicMock(return_value=False)
            inst.extract_info.return_value = info
            instances.append(inst)
        return instances

    def test_single_video_url_passes_through(self):
        info = {"id": "abc", "title": "T", "webpage_url": "https://yt.com/watch?v=abc"}
        instances = self._ydl_returning(info)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/watch?v=abc")
        assert result == [info]

    def test_plain_playlist_returns_entries(self):
        entries = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
        playlist = {"_type": "playlist", "entries": entries}
        instances = self._ydl_returning(playlist)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/playlist?list=X")
        assert result == entries

    def test_tabbed_channel_picks_videos_tab_only(self):
        tabbed = {
            "_type": "playlist",
            "entries": [
                {"_type": "playlist", "title": "X - Videos", "webpage_url": "https://yt.com/@x/videos", "url": "https://yt.com/@x/videos"},
                {"_type": "playlist", "title": "X - Live",   "webpage_url": "https://yt.com/@x/streams", "url": "https://yt.com/@x/streams"},
                {"_type": "playlist", "title": "X - Shorts", "webpage_url": "https://yt.com/@x/shorts",  "url": "https://yt.com/@x/shorts"},
            ],
        }
        videos_only = {
            "_type": "playlist",
            "entries": [
                {"id": "v1", "title": "Video 1", "webpage_url": "https://yt.com/watch?v=v1"},
                {"id": "v2", "title": "Video 2", "webpage_url": "https://yt.com/watch?v=v2"},
            ],
        }
        instances = self._ydl_returning(tabbed, videos_only)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/@x")
        assert [e["id"] for e in result] == ["v1", "v2"]

    def test_tabbed_channel_no_videos_tab_returns_empty(self):
        tabbed = {
            "_type": "playlist",
            "entries": [
                {"_type": "playlist", "title": "X - Shorts", "webpage_url": "https://yt.com/@x/shorts"},
            ],
        }
        instances = self._ydl_returning(tabbed)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/@x")
        assert result == []

    def test_after_date_filters_entries_with_upload_date(self):
        entries = [
            {"id": "old", "title": "Old", "upload_date": "20250101"},
            {"id": "new", "title": "New", "upload_date": "20260601"},
        ]
        playlist = {"_type": "playlist", "entries": entries}
        instances = self._ydl_returning(playlist)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/playlist?list=X", after_date="20260101")
        assert [e["id"] for e in result] == ["new"]

    def test_entries_without_upload_date_pass_through_under_after_date(self):
        entries = [{"id": "x", "title": "X"}]  # no upload_date field
        playlist = {"_type": "playlist", "entries": entries}
        instances = self._ydl_returning(playlist)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/playlist?list=X", after_date="20260101")
        assert [e["id"] for e in result] == ["x"]

    def test_extract_returns_none_yields_empty(self):
        instances = self._ydl_returning(None)
        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=instances):
            result = enumerate_videos("https://yt.com/bad")
        assert result == []


class TestDedupeEntriesPreferAudio:
    def test_audio_wins_over_music_video(self):
        entries = [
            {"id": "v1", "title": "Lord Of Chaos (Official Music Video)"},
            {"id": "a1", "title": "Lord Of Chaos (Audio)"},
        ]
        result = dedupe_entries_prefer_audio(entries)
        assert len(result) == 1
        assert result[0]["id"] == "a1"

    def test_audio_wins_regardless_of_order(self):
        entries = [
            {"id": "a1", "title": "Lord Of Chaos (Audio)"},
            {"id": "v1", "title": "Lord Of Chaos (Official Music Video)"},
        ]
        result = dedupe_entries_prefer_audio(entries)
        assert len(result) == 1
        assert result[0]["id"] == "a1"

    def test_unique_titles_pass_through(self):
        entries = [
            {"id": "1", "title": "Margiela"},
            {"id": "2", "title": "Catastrophe"},
        ]
        result = dedupe_entries_prefer_audio(entries)
        assert [e["id"] for e in result] == ["1", "2"]

    def test_preserves_first_seen_order(self):
        entries = [
            {"id": "1", "title": "A (Audio)"},
            {"id": "2", "title": "B (Audio)"},
            {"id": "3", "title": "A (Music Video)"},
        ]
        result = dedupe_entries_prefer_audio(entries)
        # A's slot was claimed first, B comes second; the duplicate "A (Music Video)"
        # loses on priority and the order stays [A, B].
        assert [e["id"] for e in result] == ["1", "2"]

    def test_no_marker_versions_kept_as_is(self):
        # Two entries with no audio/video marker — both have priority 1, so the
        # first one wins.
        entries = [
            {"id": "1", "title": "Track"},
            {"id": "2", "title": "Track"},
        ]
        result = dedupe_entries_prefer_audio(entries)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_entries_without_title_keyed_by_id(self):
        entries = [
            {"id": "a", "title": ""},
            {"id": "b", "title": ""},
        ]
        result = dedupe_entries_prefer_audio(entries)
        # Both lack a usable title-based key; id-based bucketing keeps them separate.
        assert {e["id"] for e in result} == {"a", "b"}


class TestDownloadTracks:
    def test_skips_already_downloaded(self, tmp_path):
        db = HistoryDB(db_path=":memory:")
        db.record_download(
            video_id="abc123", url="u", title="t", artist="a", album="al",
            channel_name="c", channel_url="cu", audio_path="p", thumbnail_path="tp",
        )

        playlist_info = {"id": "abc123", "title": "T", "entries": [_make_info()]}

        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL") as mock_ydl_cls:
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            instance.extract_info.return_value = playlist_info
            mock_ydl_cls.return_value = instance

            results = download_tracks("https://youtube.com/watch?v=abc123", db, tmp_path)

        assert len(results) == 0

    def test_downloads_new_track(self, tmp_path):
        db = HistoryDB(db_path=":memory:")
        info = _make_info()
        playlist_info = {"entries": [info]}

        (tmp_path / "abc123.wav").touch()
        (tmp_path / "abc123.jpg").touch()

        mock_extract_instance = MagicMock()
        mock_extract_instance.__enter__ = MagicMock(return_value=mock_extract_instance)
        mock_extract_instance.__exit__ = MagicMock(return_value=False)
        mock_extract_instance.extract_info.return_value = playlist_info

        mock_dl_instance = MagicMock()
        mock_dl_instance.__enter__ = MagicMock(return_value=mock_dl_instance)
        mock_dl_instance.__exit__ = MagicMock(return_value=False)
        mock_dl_instance.extract_info.return_value = info

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_extract_instance
            return mock_dl_instance

        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL", side_effect=side_effect):
            results = download_tracks("https://youtube.com/watch?v=abc123", db, tmp_path)

        assert len(results) == 1
        assert results[0].video_id == "abc123"
        assert results[0].title == "Test Song"
        assert db.is_downloaded("abc123")

    def test_returns_empty_on_extract_failure(self, tmp_path):
        db = HistoryDB(db_path=":memory:")

        with patch("yt_song_to_instrumental.downloader.yt_dlp.YoutubeDL") as mock_ydl_cls:
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            instance.extract_info.return_value = None
            mock_ydl_cls.return_value = instance

            results = download_tracks("https://youtube.com/watch?v=bad", db, tmp_path)

        assert len(results) == 0
