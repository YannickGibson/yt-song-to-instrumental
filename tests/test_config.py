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

    def test_preserve_original_video_title(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None, "preserve_original_video_title": True})
        assert s.preserve_original_video_title is True

    def test_is_uploader_fallback(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None, "is_uploader": True})
        assert s.preserve_original_video_title is True

    def test_tab_default_videos(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None})
        assert s.tab == "videos"

    def test_tab_releases(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None, "tab": "releases"})
        assert s.tab == "releases"

    def test_invalid_tab_raises(self):
        with pytest.raises(ValueError, match="source tab"):
            _parse_source({"url": "https://yt.com/c", "after_date": None, "tab": "invalid"})

    def test_create_album_playlists_default_true(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None})
        assert s.create_album_playlists is True

    def test_create_album_playlists_false(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None, "create_album_playlists": False})
        assert s.create_album_playlists is False

    def test_video_channel_url_valid(self):
        s = _parse_source({"url": "https://yt.com/c", "after_date": None, "video_channel_url": "https://yt.com/@cochise"})
        assert s.video_channel_url == "https://yt.com/@cochise"

    def test_video_channel_url_empty_raises(self):
        with pytest.raises(ValueError, match="video_channel_url"):
            _parse_source({"url": "https://yt.com/c", "after_date": None, "video_channel_url": ""})




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


class TestLabelConfigDefaultModel:
    def test_defaults_to_htdemucs_when_unset(self):
        cfg = LabelConfig(_minimal_data())
        assert cfg.default_model == "htdemucs"

    def test_explicit_inst_hq_4(self):
        cfg = LabelConfig(_minimal_data({"default_model": "inst_hq_4"}))
        assert cfg.default_model == "inst_hq_4"

    def test_explicit_htdemucs(self):
        cfg = LabelConfig(_minimal_data({"default_model": "htdemucs"}))
        assert cfg.default_model == "htdemucs"

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="default_model"):
            LabelConfig(_minimal_data({"default_model": "bogus_model"}))


class TestLabelConfigSources:
    def test_loads_multiple_sources(self):
        data = _minimal_data({
            "sources": [
                {"url": "https://yt.com/a", "after_date": "20260101"},
                {"url": "https://yt.com/b", "after_date": None, "tab": "releases"},
            ],
        })
        cfg = LabelConfig(data)
        assert len(cfg.sources) == 2
        assert cfg.sources[0].url == "https://yt.com/a"
        assert cfg.sources[0].after_date == "20260101"
        assert cfg.sources[0].tab == "videos"
        assert cfg.sources[1].after_date is None
        assert cfg.sources[1].tab == "releases"

    def test_empty_sources(self):
        cfg = LabelConfig(_minimal_data())
        assert cfg.sources == []
        assert cfg.tab == "videos"

    def test_top_level_tab_inherits_to_sources(self):
        data = _minimal_data({
            "tab": "releases",
            "sources": [
                {"url": "https://yt.com/a", "after_date": None},
            ],
        })
        cfg = LabelConfig(data)
        assert cfg.tab == "releases"
        assert cfg.sources[0].tab == "releases"


class TestLabelConfigTrimming:
    def test_trimming_defaults_when_unset(self):
        cfg = LabelConfig(_minimal_data())
        assert cfg.trim_silence is True
        assert cfg.trim_silence_threshold_db == -35.0


    def test_explicit_trimming_config(self):
        cfg = LabelConfig(_minimal_data({
            "trim_silence": True,
            "trim_silence_threshold_db": -40.5
        }))
        assert cfg.trim_silence is True
        assert cfg.trim_silence_threshold_db == -40.5


class TestLabelConfigShorts:
    def test_shorts_defaults_when_unset(self):
        cfg = LabelConfig(_minimal_data())
        assert cfg.upload_short is False
        assert cfg.upload_short_if_music_video is False
        assert "<full-video-url>" in cfg.short_description_template

    def test_explicit_upload_short(self):
        cfg = LabelConfig(_minimal_data({"upload_short": True}))
        assert cfg.upload_short is True
        assert cfg.upload_short_if_music_video is False

    def test_explicit_upload_short_if_music_video(self):
        cfg = LabelConfig(_minimal_data({"upload_short_if_music_video": True}))
        assert cfg.upload_short is False
        assert cfg.upload_short_if_music_video is True

    def test_both_shorts_flags_true_raises_error(self):
        with pytest.raises(ValueError, match="both 'upload_short' and 'upload_short_if_music_video' cannot be true"):
            LabelConfig(_minimal_data({
                "upload_short": True,
                "upload_short_if_music_video": True,
            }))

    def test_custom_short_description_template(self):
        data = _minimal_data({
            "templates": {
                "video_title": "<artist-name>",
                "video_description": "D",
                "album_playlist_name": "<artist-name> — <album-name>",
                "artist_playlist_name": "<artist-name>",
                "short_description": "Watch full video: <full-video-url>\n<video-title>",
            },
        })
        cfg = LabelConfig(data)
        assert cfg.short_description_template == "Watch full video: <full-video-url>\n<video-title>"

    def test_invalid_tag_in_short_description_raises(self):
        data = _minimal_data({
            "templates": {
                "video_title": "<artist-name>",
                "video_description": "D",
                "album_playlist_name": "<artist-name> — <album-name>",
                "artist_playlist_name": "<artist-name>",
                "short_description": "Watch: <invalid-tag>",
            },
        })
        with pytest.raises(ValueError, match="templates.short_description"):
            LabelConfig(data)


