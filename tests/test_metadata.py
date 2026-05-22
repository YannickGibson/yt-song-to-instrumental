import pytest

from yt_song_to_instrumental.config import ArtistAliasResolver
from yt_song_to_instrumental.metadata import (
    render_description,
    render_playlist_name,
    render_template,
    render_title,
    render_video_title,
    strip_title_parentheticals,
    validate_template_tags,
    version_priority,
    _sanitize_for_hashtag,
    _sanitize_text,
)
from yt_song_to_instrumental.constants import YOUTUBE_TITLE_MAX_LENGTH


class TestStripTitleParentheticals:
    def test_strips_official_audio(self):
        assert strip_title_parentheticals("Catastrophe (Official Audio)") == "Catastrophe"

    def test_strips_noise_but_keeps_feat(self):
        # (feat. X) must survive so title-feat extraction still works as a
        # fallback when YTMusic's artists list misses a collaborator.
        assert strip_title_parentheticals("Nocturne ft. Hollow Cair (Official Music Video) (feat. Hollow Cair)") == "Nocturne ft. Hollow Cair (feat. Hollow Cair)"

    def test_strips_noise_but_keeps_ft_no_space(self):
        assert strip_title_parentheticals("Brass Ring (Official Audio) (ft.Lil Quark)") == "Brass Ring (ft.Lil Quark)"

    def test_strips_leading_and_internal(self):
        assert strip_title_parentheticals("(Bonus) Song Name (Audio)") == "Song Name"

    def test_unchanged_when_no_parens(self):
        assert strip_title_parentheticals("velvetine") == "velvetine"

    def test_collapses_whitespace_around_strip(self):
        assert strip_title_parentheticals("Song   (Audio)   Title") == "Song Title"


class TestSanitize:
    def test_sanitize_for_hashtag_single(self):
        assert _sanitize_for_hashtag("Lil Bram") == "#lilbram"
        assert _sanitize_for_hashtag("B$B Flux") == "#bbflux"
        assert _sanitize_for_hashtag("37 Drifters") == "#37drifters"

    def test_sanitize_for_hashtag_multiple_artists(self):
        assert _sanitize_for_hashtag("GLOOMHOUR, LIL EMBER") == "#gloomhour #lilember"
        assert _sanitize_for_hashtag("Riku Vex & Mara Doon") == "#rikuvex #maradoon"
        assert _sanitize_for_hashtag("Wynd feat. Kid Nimbus") == "#wynd #kidnimbus"
        assert _sanitize_for_hashtag("Toller / Parnell") == "#toller #parnell"

    def test_sanitize_text_strips_angle_brackets(self):
        assert _sanitize_text("<script>alert</script>") == "scriptalert/script"
        assert _sanitize_text("  hello  ") == "hello"


class TestRenderTemplate:
    def test_replaces_all_tags(self):
        template = "<artist-name> — <track-title> | <album-name> | <original-url> | <original-channel-url> | <model-name> | <label-name> | #<artist-tag>"
        result = render_template(
            template,
            artist_name="Riku Vex",
            track_title="Stargazer",
            album_name="Longer Days",
            original_url="https://youtube.com/watch?v=abc",
            original_channel_url="https://youtube.com/@ovosound",
            model_name="HTDemucs",
            label_name="Crescent",
        )
        assert "Riku Vex" in result
        assert "Stargazer" in result
        assert "Longer Days" in result
        assert "https://youtube.com/watch?v=abc" in result
        assert "https://youtube.com/@ovosound" in result
        assert "HTDemucs" in result
        assert "Crescent" in result
        assert "#rikuvex" in result.lower()

    def test_original_url_not_substituted_inside_original_channel_url(self):
        # Guard against str.replace ordering bugs: <original-url> must not
        # match as a substring of <original-channel-url>.
        result = render_template(
            "<original-channel-url>",
            original_url="WRONG",
            original_channel_url="https://yt.com/@x",
        )
        assert result == "https://yt.com/@x"

    def test_empty_values_produce_empty_strings(self):
        result = render_template("<artist-name> — <track-title>")
        assert result == " — "


class TestRenderTitle:
    def test_basic_title(self):
        template = "<artist-name> — <track-title> (Instrumental)"
        result = render_title(template, artist_name="Riku Vex", track_title="Stargazer")
        assert result == "Riku Vex — Stargazer (Instrumental)"

    def test_truncates_long_title(self):
        template = "<artist-name> — <track-title> (Instrumental)"
        result = render_title(
            template,
            artist_name="A Very Long Artist Name That Goes On",
            track_title="An Extremely Long Track Title That Should Cause Truncation Because It Exceeds The Limit",
        )
        assert len(result) <= YOUTUBE_TITLE_MAX_LENGTH
        assert result.endswith("...")


class TestRenderDescription:
    def test_full_description(self):
        template = "<artist-name> — <track-title>\nOriginal: <original-url>\nChannel: <original-channel-url>\n#<artist-tag>"
        result = render_description(
            template,
            artist_name="Riku Vex",
            track_title="Stargazer",
            original_url="https://youtube.com/watch?v=abc",
            original_channel_url="https://youtube.com/@ovosound",
        )
        assert "Riku Vex — Stargazer" in result
        assert "https://youtube.com/watch?v=abc" in result
        assert "https://youtube.com/@ovosound" in result
        assert "#rikuvex" in result.lower()

    def test_video_title_tag_substituted(self):
        # Description that delegates the first line to <video-title> so it
        # mirrors the rendered upload title exactly.
        template = "<video-title>\n\nOriginal: <original-url>"
        result = render_description(
            template,
            artist_name="Nyte Vandal",
            track_title="Nyte Vandal & @hollowcair - the cipher",
            video_title="Nyte Vandal & @hollowcair - the cipher (Instrumental)",
            original_url="https://yt.com/x",
        )
        assert result.startswith("Nyte Vandal & @hollowcair - the cipher (Instrumental)")
        # The raw artist/track combo must NOT also appear duplicated.
        assert "Nyte Vandal — Nyte Vandal" not in result


class TestVersionPriority:
    def test_audio_wins(self):
        assert version_priority("Track (Audio)") == 0
        assert version_priority("Track (Official Audio)") == 0

    def test_music_video_loses(self):
        assert version_priority("Track (Music Video)") == 2
        assert version_priority("Track (Official Music Video)") == 2
        assert version_priority("Track (Official Video)") == 2

    def test_no_marker_is_neutral(self):
        assert version_priority("Track") == 1
        assert version_priority("Track (Bonus)") == 1


class TestRenderPlaylistName:
    def test_artist_playlist(self):
        template = "<artist-name> Instrumentals"
        result = render_playlist_name(template, artist_name="Riku Vex")
        assert result == "Riku Vex Instrumentals"

    def test_album_playlist(self):
        template = "<artist-name> — <album-name> Instrumentals"
        result = render_playlist_name(template, artist_name="Riku Vex", album_name="Quiet Hours")
        assert result == "Riku Vex — Quiet Hours Instrumentals"


_TPL = "<artist-name> — <track-title> (Instrumental)"


def _aliases(*groups: list[str]) -> ArtistAliasResolver:
    return ArtistAliasResolver(list(groups))


class TestRenderVideoTitle:
    def test_solo_track_no_features(self):
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="velvetine",
            all_artists=["Nyte Vandal"],
            album_name="",
            model_name="HTDemucs",
            label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — velvetine (Instrumental)"

    def test_solo_track_with_one_feature(self):
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Harborline",
            all_artists=["Nyte Vandal", "Hollow Cair"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — Harborline (feat. Hollow Cair) (Instrumental)"

    def test_solo_track_with_multiple_features(self):
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Past Curfew",
            all_artists=["Nyte Vandal", "Plastic Vow", "Hollow Cair"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — Past Curfew (feat. Plastic Vow & Hollow Cair) (Instrumental)"

    def test_alias_prefix_stripped(self):
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nyte Vand$l - Change",
            all_artists=["Nyte Vandal"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(["Nyte Vandal", "Nyte Vand$l"]),
        )
        assert result == "Nyte Vandal — Change (Instrumental)"

    def test_multi_artist_credit_in_title_swaps_handle_for_canonical(self):
        # @-handle variant gets replaced by the canonical name because the
        # alias group provides a non-@ form.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nyte Vandal & @hollowcair - the cipher",
            all_artists=["Nyte Vandal", "Hollow Cair"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(["Hollow Cair", "@hollowcair"]),
        )
        assert result == "Nyte Vandal & Hollow Cair - the cipher (Instrumental)"

    def test_multi_artist_credit_keeps_handle_when_no_canonical_alias(self):
        # No alias group for @hollowcair → keep verbatim.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nyte Vandal & @hollowcair - the cipher",
            all_artists=["Nyte Vandal"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal & @hollowcair - the cipher (Instrumental)"

    def test_unrecognized_prefix_uses_template_unchanged(self):
        # LHS "Some Other" is not a primary variant and not multi-artist; treat
        # the whole title as the track name.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Some Other - Thing",
            all_artists=["Nyte Vandal"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — Some Other - Thing (Instrumental)"

    def test_features_canonicalized_via_aliases(self):
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Driftling",
            all_artists=["Nyte Vandal", "GWC"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(["Glasswing Crew", "GWC"]),
        )
        assert result == "Nyte Vandal — Driftling (feat. Glasswing Crew) (Instrumental)"

    def test_unparenthesized_feat_is_extracted_and_canonicalized(self):
        # "Nocturne ft. Hollow Cair" → ft. credit pulled out, no double-feat.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nocturne ft. Hollow Cair",
            all_artists=["Nyte Vandal", "Hollow Cair"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — Nocturne (feat. Hollow Cair) (Instrumental)"

    def test_unparenthesized_feat_alias_canonicalized(self):
        # "Driftling ft. GWC" with alias GWC→Glasswing Crew.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Driftling ft. GWC",
            all_artists=["Nyte Vandal"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(["Glasswing Crew", "GWC"]),
        )
        assert result == "Nyte Vandal — Driftling (feat. Glasswing Crew) (Instrumental)"

    def test_no_double_feat_when_paren_and_unparen_overlap(self):
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nocturne ft. Hollow Cair (feat. Hollow Cair)",
            all_artists=["Nyte Vandal", "Hollow Cair"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — Nocturne (feat. Hollow Cair) (Instrumental)"

    def test_whitespace_collapsed_in_verbatim_case(self):
        # Original title has a double space; verbatim emission should collapse it.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nyte Vandal & @hollowcair  - the cipher",
            all_artists=["Nyte Vandal", "Hollow Cair"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(["Hollow Cair", "@hollowcair"]),
        )
        assert "  " not in result

    def test_primary_alone_then_no_features(self):
        # Title is "Nyte Vandal - velvetine" — strip prefix, no features known.
        result = render_video_title(
            _TPL,
            primary_artist="Nyte Vandal",
            raw_title="Nyte Vandal - velvetine",
            all_artists=["Nyte Vandal"],
            album_name="", model_name="HTDemucs", label_name="L",
            aliases=_aliases(),
        )
        assert result == "Nyte Vandal — velvetine (Instrumental)"


class TestValidateTemplateTags:
    def test_accepts_only_supported_tags(self):
        # All currently-supported tags in one template.
        template = (
            "<artist-name> <track-title> <album-name> <original-url> "
            "<original-channel-url> <model-name> <label-name> <artist-tag> "
            "<channel-url> <video-title>"
        )
        validate_template_tags(template, "templates.test")

    def test_accepts_empty_template(self):
        validate_template_tags("", "templates.test")

    def test_accepts_template_with_no_tags(self):
        validate_template_tags("Just plain text with no angle brackets.", "templates.test")

    def test_rejects_unknown_tag(self):
        with pytest.raises(ValueError, match="Unsupported template tag"):
            validate_template_tags("Hello <bogus-tag>", "templates.test")

    def test_rejects_old_original_channel_tag(self):
        # The renamed tag must be flagged so a stale label.yml from before the
        # rename fails fast instead of leaking the literal "<original-channel>"
        # into a public upload.
        with pytest.raises(ValueError, match="<original-channel>"):
            validate_template_tags("Channel: <original-channel>", "templates.video_description")

    def test_reports_all_unknowns_and_template_name(self):
        with pytest.raises(ValueError) as exc:
            validate_template_tags(
                "<artist-name> <typo-tag> and <another-bad>",
                "templates.video_title",
            )
        msg = str(exc.value)
        assert "templates.video_title" in msg
        assert "<typo-tag>" in msg
        assert "<another-bad>" in msg

    def test_ignores_uppercase_or_closing_brackets(self):
        # Validator pattern is kebab-case lowercase only. Things like
        # closing-tag form "</foo>" or "<Foo>" don't look like template tags
        # and so don't trigger the check.
        validate_template_tags("</closing> <CamelCase>", "templates.test")

