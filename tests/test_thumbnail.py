from pathlib import Path
from unittest.mock import patch

from yt_song_to_instrumental.thumbnail import fetch_thumbnail, get_thumbnail_for_track


class TestFetchThumbnail:
    def test_returns_path_on_success(self, tmp_path):
        def fake_retrieve(url, path):
            Path(path).write_bytes(b"\xff\xd8" * 1000)

        with patch("yt_song_to_instrumental.thumbnail.urllib.request.urlretrieve", side_effect=fake_retrieve):
            result = fetch_thumbnail("abc123", tmp_path)

        assert result.is_file()
        assert "abc123" in result.name

    def test_returns_none_on_failure(self, tmp_path):
        def fake_retrieve(url, path):
            Path(path).write_bytes(b"")

        with patch("yt_song_to_instrumental.thumbnail.urllib.request.urlretrieve", side_effect=fake_retrieve):
            result = fetch_thumbnail("abc123", tmp_path)

        assert result is None

    def test_tries_multiple_resolutions(self, tmp_path):
        calls = []

        def fake_retrieve(url, path):
            calls.append(url)
            if "maxresdefault" in url:
                Path(path).write_bytes(b"tiny")
            elif "sddefault" in url:
                Path(path).write_bytes(b"\xff\xd8" * 1000)

        with patch("yt_song_to_instrumental.thumbnail.urllib.request.urlretrieve", side_effect=fake_retrieve):
            result = fetch_thumbnail("abc123", tmp_path)

        assert len(calls) >= 2
        assert result.exists()


class TestGetThumbnailForTrack:
    def test_uses_existing_thumbnail(self, tmp_path):
        existing = tmp_path / "existing.jpg"
        existing.write_bytes(b"\xff\xd8" * 1000)

        result = get_thumbnail_for_track("abc123", existing, tmp_path)
        assert result == existing

    def test_fetches_if_existing_missing(self, tmp_path):
        def fake_retrieve(url, path):
            Path(path).write_bytes(b"\xff\xd8" * 1000)

        with patch("yt_song_to_instrumental.thumbnail.urllib.request.urlretrieve", side_effect=fake_retrieve):
            result = get_thumbnail_for_track("abc123", Path(""), tmp_path)

        assert result.is_file()

    def test_fetches_if_existing_is_directory(self, tmp_path):
        thumbnail = tmp_path / "fetched.jpg"
        thumbnail.write_bytes(b"image")
        with patch("yt_song_to_instrumental.thumbnail.fetch_thumbnail", return_value=thumbnail) as fetch:
            result = get_thumbnail_for_track("abc123", tmp_path, tmp_path)
        fetch.assert_called_once_with("abc123", tmp_path)
        assert result == thumbnail
