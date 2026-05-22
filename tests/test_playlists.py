from unittest.mock import MagicMock, patch, call

from yt_song_to_instrumental.config import ArtistAliasResolver, LabelConfig
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.playlists import (
    assign_to_playlists,
    extract_featured_artists,
    get_or_create_album_playlist,
    get_or_create_artist_playlist,
    project_playlist_names,
    split_artists,
)

# All names below are fabricated — no real artists, albums, or tracks.


def _make_label_config(
    aliases: list[list[str]] | None = None,
    create_playlists_for_collaborators: bool = True,
) -> LabelConfig:
    data = {
        "channel": {"name": "Test Instrumentals", "description": "Test desc"},
        "label": {"name": "TestLabel"},
        "templates": {
            "video_title": "<artist-name> — <track-title> (Instrumental)",
            "video_description": "Desc",
            "album_playlist_name": "<artist-name> — <album-name> Instrumentals",
            "artist_playlist_name": "<artist-name> Instrumentals",
        },
        "create_playlists_for_collaborators": create_playlists_for_collaborators,
        "sources": [],
    }
    if aliases is not None:
        data["artist_aliases"] = aliases
    return LabelConfig(data)


def _make_mock_service(playlist_id: str = "PL_new_123", existing_privacy: str = "public"):
    service = MagicMock()
    service.playlists().insert().execute.return_value = {"id": playlist_id}
    # Response shape for _ensure_playlist_privacy's playlists.list() call.
    service.playlists().list().execute.return_value = {
        "items": [{
            "snippet": {"title": "Existing Playlist", "description": ""},
            "status": {"privacyStatus": existing_privacy},
        }],
    }
    return service


class TestGetOrCreateArtistPlaylist:
    def test_creates_new_playlist(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config()
        service = _make_mock_service("PL_artist_1")

        result = get_or_create_artist_playlist(service, db, config, "Riku Vex")

        assert result == "PL_artist_1"
        record = db.get_playlist("artist", "Riku Vex")
        assert record is not None
        assert record.youtube_playlist_id == "PL_artist_1"

    def test_returns_existing_playlist(self):
        db = HistoryDB(db_path=":memory:")
        db.record_playlist("artist", "Riku Vex", None, "PL_existing")
        config = _make_label_config()
        service = _make_mock_service(existing_privacy="public")

        result = get_or_create_artist_playlist(service, db, config, "Riku Vex", privacy="public")

        assert result == "PL_existing"
        # Privacy already matches → no update.
        service.playlists().update.assert_not_called()

    def test_existing_playlist_privacy_synced_when_mismatched(self):
        db = HistoryDB(db_path=":memory:")
        db.record_playlist("artist", "Riku Vex", None, "PL_existing")
        config = _make_label_config()
        service = _make_mock_service(existing_privacy="unlisted")

        result = get_or_create_artist_playlist(service, db, config, "Riku Vex", privacy="public")

        assert result == "PL_existing"
        # Playlist was unlisted, video is public → playlist re-synced to public.
        service.playlists().update.assert_called_once()


class TestGetOrCreateAlbumPlaylist:
    def test_creates_new_playlist(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config()
        service = _make_mock_service("PL_album_1")

        result = get_or_create_album_playlist(service, db, config, "Riku Vex", "Quiet Hours")

        assert result == "PL_album_1"
        record = db.get_playlist("album", "Riku Vex", "Quiet Hours")
        assert record is not None

    def test_returns_existing_playlist(self):
        db = HistoryDB(db_path=":memory:")
        db.record_playlist("album", "Riku Vex", "Quiet Hours", "PL_existing_album")
        config = _make_label_config()
        service = _make_mock_service(existing_privacy="public")

        result = get_or_create_album_playlist(service, db, config, "Riku Vex", "Quiet Hours", privacy="public")

        assert result == "PL_existing_album"
        service.playlists().update.assert_not_called()

    def test_existing_album_playlist_privacy_synced(self):
        db = HistoryDB(db_path=":memory:")
        db.record_playlist("album", "Riku Vex", "Quiet Hours", "PL_existing_album")
        config = _make_label_config()
        service = _make_mock_service(existing_privacy="private")

        get_or_create_album_playlist(service, db, config, "Riku Vex", "Quiet Hours", privacy="public")

        service.playlists().update.assert_called_once()


class TestSplitArtists:
    def test_single_artist(self):
        assert split_artists("Riku Vex") == ["Riku Vex"]

    def test_comma_separated(self):
        assert split_artists("GLOOMHOUR, LIL EMBER") == ["GLOOMHOUR", "LIL EMBER"]

    def test_ampersand(self):
        assert split_artists("Riku Vex & Mara Doon") == ["Riku Vex", "Mara Doon"]

    def test_feat(self):
        assert split_artists("Riku Vex feat. Sola Quen") == ["Riku Vex", "Sola Quen"]

    def test_ft(self):
        assert split_artists("Riku Vex ft Lil Bram") == ["Riku Vex", "Lil Bram"]

    def test_slash(self):
        assert split_artists("Riku Vex / Mara Doon") == ["Riku Vex", "Mara Doon"]

    def test_multiple_separators(self):
        assert split_artists("A, B & C feat. D") == ["A", "B", "C", "D"]


class TestExtractFeaturedArtists:
    def test_no_feat(self):
        assert extract_featured_artists("Static Crown") == []

    def test_feat_single(self):
        assert extract_featured_artists("Driftling (feat. GWC)") == ["GWC"]

    def test_feat_dot(self):
        assert extract_featured_artists("Nocturne (feat. Hollow Cair)") == ["Hollow Cair"]

    def test_ft_no_dot(self):
        assert extract_featured_artists("Track (ft Lil Bram)") == ["Lil Bram"]

    def test_feat_multiple_ampersand(self):
        assert extract_featured_artists("Just So (feat. Lil Echo Stax & Hollow Cair)") == [
            "Lil Echo Stax", "Hollow Cair",
        ]

    def test_feat_multiple_comma(self):
        assert extract_featured_artists("Brass Ring (feat. Border Czar & Lil Quark)") == [
            "Border Czar", "Lil Quark",
        ]


class TestAssignToPlaylists:
    def test_primary_artist_and_album(self):
        db = HistoryDB(db_path=":memory:")
        db.record_playlist("artist", "Riku Vex", None, "PL_artist")
        db.record_playlist("album", "Riku Vex", "Quiet Hours", "PL_album")
        config = _make_label_config()
        service = MagicMock()

        assign_to_playlists(service, db, config, "yt_vid_123", "Riku Vex", "Quiet Hours", "Riku Vex")

        assert service.playlistItems().insert.call_count == 2

    def test_skips_album_playlist_when_no_album(self):
        db = HistoryDB(db_path=":memory:")
        db.record_playlist("artist", "Riku Vex", None, "PL_artist")
        config = _make_label_config()
        service = MagicMock()

        assign_to_playlists(service, db, config, "yt_vid_123", "Riku Vex", "", "Riku Vex")

        assert service.playlistItems().insert.call_count == 1

    def test_unknown_collaborator_gets_no_playlist(self):
        # Primary always gets a playlist; an unknown collaborator does not.
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config()  # no aliases
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "fauxpelt, Dj Quartz", "",
            primary_artist="fauxpelt",
        )

        assert db.get_playlist("artist", "fauxpelt") is not None
        assert db.get_playlist("artist", "Dj Quartz") is None
        assert service.playlistItems().insert.call_count == 1

    def test_known_collaborator_gets_a_playlist(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(aliases=[["Nyte Vandal"], ["Hollow Cair"]])
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "Nyte Vandal, Hollow Cair", "",
            primary_artist="Nyte Vandal",
        )

        assert db.get_playlist("artist", "Nyte Vandal") is not None
        assert db.get_playlist("artist", "Hollow Cair") is not None
        assert service.playlistItems().insert.call_count == 2

    def test_album_playlist_keyed_on_primary_artist(self):
        # Even when the YTMusic artist field is some odd multi-artist string,
        # the album playlist is credited to the channel's primary artist.
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config()
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "fauxpelt archive, Dj Quartz", "Some Album",
            primary_artist="fauxpelt",
        )

        assert db.get_playlist("album", "fauxpelt", "Some Album") is not None
        assert db.get_playlist("album", "fauxpelt archive, Dj Quartz", "Some Album") is None

    def test_featured_known_artist_from_title(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(aliases=[["Glasswing Crew", "GWC"]])
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "Nyte Vandal", "",
            primary_artist="Nyte Vandal", track_title="Driftling (feat. GWC)",
        )

        assert db.get_playlist("artist", "Nyte Vandal") is not None
        assert db.get_playlist("artist", "Glasswing Crew") is not None
        assert db.get_playlist("artist", "GWC") is None
        assert service.playlistItems().insert.call_count == 2

    def test_featured_unknown_artist_from_title_skipped(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config()  # no aliases
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "Nyte Vandal", "",
            primary_artist="Nyte Vandal", track_title="Song (feat. Some Guest)",
        )

        assert db.get_playlist("artist", "Nyte Vandal") is not None
        assert db.get_playlist("artist", "Some Guest") is None
        assert service.playlistItems().insert.call_count == 1

    def test_alias_deduplicates_primary_and_collaborator(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(aliases=[["Glasswing Crew", "GWC", "Glasswing"]])
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "GWC", "",
            primary_artist="GWC", track_title="Track (feat. Glasswing)",
        )

        assert db.get_playlist("artist", "Glasswing Crew") is not None
        # primary GWC and featured Glasswing both resolve to the same canonical
        assert service.playlistItems().insert.call_count == 1


class TestFeaturesToggle:
    def test_features_off_only_primary_artist(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(
            aliases=[["Artist A"], ["Artist B"]],
            create_playlists_for_collaborators=False,
        )
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "Artist A, Artist B", "",
            primary_artist="Artist A",
        )

        # Flag off → only the primary, even though Artist B is alias-known.
        assert db.get_playlist("artist", "Artist A") is not None
        assert db.get_playlist("artist", "Artist B") is None
        assert service.playlistItems().insert.call_count == 1

    def test_features_off_ignores_feat_in_title(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(
            aliases=[["Hollow Cair"]],
            create_playlists_for_collaborators=False,
        )
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "Nyte Vandal", "",
            primary_artist="Nyte Vandal", track_title="Song (feat. Hollow Cair)",
        )

        assert db.get_playlist("artist", "Nyte Vandal") is not None
        assert db.get_playlist("artist", "Hollow Cair") is None
        assert service.playlistItems().insert.call_count == 1

    def test_features_off_resolves_primary_through_alias(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(
            aliases=[["Glasswing Crew", "GWC"]],
            create_playlists_for_collaborators=False,
        )
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "GWC", "", primary_artist="GWC",
        )

        assert db.get_playlist("artist", "Glasswing Crew") is not None
        assert db.get_playlist("artist", "GWC") is None

    def test_features_off_keeps_album_playlist(self):
        db = HistoryDB(db_path=":memory:")
        config = _make_label_config(create_playlists_for_collaborators=False)
        service = _make_mock_service("PL_new")

        assign_to_playlists(
            service, db, config, "yt_vid_123", "fauxpelt", "Joint Album",
            primary_artist="fauxpelt",
        )

        assert db.get_playlist("artist", "fauxpelt") is not None
        assert db.get_playlist("album", "fauxpelt", "Joint Album") is not None
        assert service.playlistItems().insert.call_count == 2


class TestProjectPlaylistNames:
    def test_unknown_collaborators_dropped_primary_kept(self):
        config = _make_label_config(create_playlists_for_collaborators=True)
        artist_titles, album_title = project_playlist_names(
            config, "Riku Vex & Mara Doon", "Quiet Hours", "Track (feat. Lil Bram)",
            primary_artist="Riku Vex",
        )
        # None of the artists are alias-known → only primary survives.
        assert artist_titles == ["Riku Vex Instrumentals"]
        # Album playlist credited to the primary artist.
        assert album_title == "Riku Vex — Quiet Hours Instrumentals"

    def test_known_collaborators_kept(self):
        config = _make_label_config(
            aliases=[["Riku Vex"], ["Mara Doon"]],
            create_playlists_for_collaborators=True,
        )
        artist_titles, _ = project_playlist_names(
            config, "Riku Vex & Mara Doon", "Quiet Hours", "Track",
            primary_artist="Riku Vex",
        )
        assert artist_titles == ["Riku Vex Instrumentals", "Mara Doon Instrumentals"]

    def test_features_off_primary_only(self):
        config = _make_label_config(create_playlists_for_collaborators=False)
        artist_titles, album_title = project_playlist_names(
            config, "Riku Vex & Mara Doon", "Quiet Hours", "Track (feat. Lil Bram)",
            primary_artist="Riku Vex",
        )
        assert artist_titles == ["Riku Vex Instrumentals"]
        assert album_title == "Riku Vex — Quiet Hours Instrumentals"

    def test_no_album(self):
        config = _make_label_config(create_playlists_for_collaborators=True)
        artist_titles, album_title = project_playlist_names(
            config, "Nyte Vandal", "", "Downfall", primary_artist="Nyte Vandal",
        )
        assert artist_titles == ["Nyte Vandal Instrumentals"]
        assert album_title is None

    def test_alias_canonicalizes_featured(self):
        config = _make_label_config(
            aliases=[["Glasswing Crew", "GWC"]],
            create_playlists_for_collaborators=True,
        )
        artist_titles, _ = project_playlist_names(
            config, "Nyte Vandal", "", "Driftling (feat. GWC)",
            primary_artist="Nyte Vandal",
        )
        assert artist_titles == [
            "Nyte Vandal Instrumentals",
            "Glasswing Crew Instrumentals",
        ]


class TestArtistAliasResolver:
    def test_resolves_to_canonical(self):
        r = ArtistAliasResolver([["Glasswing Crew", "GWC", "Glasswing"]])
        assert r.resolve("GWC") == "Glasswing Crew"
        assert r.resolve("Glasswing") == "Glasswing Crew"
        assert r.resolve("Glasswing Crew") == "Glasswing Crew"

    def test_case_insensitive(self):
        r = ArtistAliasResolver([["Glasswing Crew", "gwc"]])
        assert r.resolve("GWC") == "Glasswing Crew"
        assert r.resolve("gwc") == "Glasswing Crew"

    def test_unknown_name_passes_through(self):
        r = ArtistAliasResolver([["Glasswing Crew", "GWC"]])
        assert r.resolve("Nyte Vandal") == "Nyte Vandal"

    def test_multiple_groups(self):
        r = ArtistAliasResolver([
            ["Glasswing Crew", "GWC"],
            ["Plastic Vow", "Plastic V0w"],
        ])
        assert r.resolve("GWC") == "Glasswing Crew"
        assert r.resolve("Plastic V0w") == "Plastic Vow"

    def test_empty_groups(self):
        r = ArtistAliasResolver([])
        assert r.resolve("Anyone") == "Anyone"

    def test_single_entry_group_is_known(self):
        # A one-name group registers the artist as "known" (so they get a
        # playlist) but declares no alias variants.
        r = ArtistAliasResolver([["Solo"]])
        assert r.resolve("Solo") == "Solo"
        assert r.is_known("Solo") is True
        assert r.variants_of("Solo") == ["Solo"]

    def test_is_known_true_for_canonical_and_variants(self):
        r = ArtistAliasResolver([["Glasswing Crew", "GWC", "Glasswing"]])
        assert r.is_known("Glasswing Crew") is True
        assert r.is_known("GWC") is True
        assert r.is_known("glasswing") is True  # case-insensitive

    def test_is_known_false_for_unknown(self):
        r = ArtistAliasResolver([["Glasswing Crew", "GWC"]])
        assert r.is_known("Plastic Vow") is False

    def test_is_known_false_with_no_groups(self):
        r = ArtistAliasResolver([])
        assert r.is_known("Anyone") is False

    def test_variants_of_returns_full_group(self):
        r = ArtistAliasResolver([["Nyte Vandal", "Nyte Vand$l", "NyteVandalCRR"]])
        result = r.variants_of("Nyte Vandal")
        assert "Nyte Vandal" in result
        assert "Nyte Vand$l" in result
        assert "NyteVandalCRR" in result

    def test_variants_of_unknown_returns_self(self):
        r = ArtistAliasResolver([["Nyte Vandal", "Nyte Vand$l"]])
        assert r.variants_of("Some Random") == ["Some Random"]

    def test_variants_of_case_insensitive(self):
        r = ArtistAliasResolver([["Glasswing Crew", "GWC"]])
        # Querying with a non-canonical case still resolves to the group.
        assert "Glasswing Crew" in r.variants_of("glasswing crew")
