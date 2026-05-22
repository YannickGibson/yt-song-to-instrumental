import pytest

from yt_song_to_instrumental.config import LabelConfig, Source, _parse_source


def _minimal_data(overrides: dict | None = None) -> dict:
    data = {
        "channel": {"name": "Test", "description": "T"},
        "label": {"name": "TestLabel"},
        "templates": {
            "video_title": "<artist-name>",
            "video_description": "D",
            "album_playlist_name": "<artist-name> — <album-name>",
            "artist_playlist_name": "<artist-name>",
        },
        "create_playlists_for_collaborators": True,
        "sources": [],
    }
    if overrides:
        data.update(overrides)
    return data


class TestLabelConfigRequiredKeys:
    def test_missing_create_playlists_for_collaborators_raises(self):
        data = _minimal_data()
        del data["create_playlists_for_collaborators"]
        with pytest.raises(KeyError):
            LabelConfig(data)

    def test_missing_sources_raises(self):
        data = _minimal_data()
        del data["sources"]
        with pytest.raises(KeyError):
            LabelConfig(data)


class TestSourceParsing:
    def test_valid_after_date(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": "20260101"})
        assert s == Source(url="https://yt.com/c", after_date="20260101")

    def test_null_after_date_ok(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None})
        assert s.after_date is None

    def test_bad_after_date_format_raises(self):
        with pytest.raises(ValueError):
            _parse_source({"url": "https://yt.com/c", "after_date": "2026-01-01"})

    def test_short_after_date_raises(self):
        with pytest.raises(ValueError):
            _parse_source({"url": "https://yt.com/c", "after_date": "202601"})

    def test_empty_url_raises(self):
        with pytest.raises(ValueError):
            _parse_source({"url": "", "after_date": None})

    def test_non_string_url_raises(self):
        with pytest.raises(ValueError):
            _parse_source({"url": 12345, "after_date": None})


class TestLabelConfigTemplateValidation:
    def test_unsupported_tag_in_video_title_raises_at_load_time(self):
        data = _minimal_data({
            "templates": {
                "video_title": "<artist-name> <bogus-tag>",
                "video_description": "D",
                "album_playlist_name": "<artist-name> — <album-name>",
                "artist_playlist_name": "<artist-name>",
            },
        })
        with pytest.raises(ValueError, match="templates.video_title"):
            LabelConfig(data)

    def test_stale_original_channel_tag_is_rejected(self):
        data = _minimal_data({
            "templates": {
                "video_title": "<artist-name>",
                "video_description": "Channel: <original-channel>",
                "album_playlist_name": "<artist-name> — <album-name>",
                "artist_playlist_name": "<artist-name>",
            },
        })
        with pytest.raises(ValueError, match="<original-channel>"):
            LabelConfig(data)

    def test_new_original_channel_url_tag_is_accepted(self):
        data = _minimal_data({
            "templates": {
                "video_title": "<artist-name>",
                "video_description": "Channel: <original-channel-url>",
                "album_playlist_name": "<artist-name> — <album-name>",
                "artist_playlist_name": "<artist-name>",
            },
        })
        LabelConfig(data)


class TestLabelConfigSources:
    def test_loads_multiple_sources(self):
        data = _minimal_data({
            "sources": [
                {"url": "https://yt.com/a", "after_date": "20260101"},
                {"url": "https://yt.com/b", "after_date": None},
            ],
        })
        cfg = LabelConfig(data)
        assert len(cfg.sources) == 2
        assert cfg.sources[0].url == "https://yt.com/a"
        assert cfg.sources[0].after_date == "20260101"
        assert cfg.sources[1].after_date is None

    def test_empty_sources(self):
        cfg = LabelConfig(_minimal_data())
        assert cfg.sources == []
