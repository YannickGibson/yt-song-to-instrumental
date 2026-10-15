import pytest

from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.song_identity import normalize_song_identity


@pytest.mark.parametrize("title,artist,matches", [
    ("Example Song .", "Example Artist", True),
    ("EXAMPLE SONG…", "example artist", True),
    ("Example Song (Remix)", "Example Artist", False),
    ("Example Song (Live)", "Example Artist", False),
    ("Example Song (Sped Up)", "Example Artist", False),
    ("Example Song", "Different Artist", False),
    ("Example Song", "", False),
])
def test_persistent_cross_source_identity(tmp_path, title, artist, matches):
    path = tmp_path / "history.db"
    db = HistoryDB(path)
    for source, name, performer in [("old", "Example Song", "Example Artist"), ("new", title, artist)]:
        db.record_download(source, "url", name, performer, "", "channel", "url", "audio", "thumb")
    db.record_upload("old", "old-model", "published", "public")
    db.close()
    db = HistoryDB(path)
    result = db.get_duplicate_song_upload("new")
    assert (result is not None) == matches
    if matches:
        assert result.youtube_upload_id == "published"
        assert result.video_id == "old"
    assert db.get_existing_upload("new") is None
    db.close()


def test_internal_punctuation_and_version_qualifiers_survive():
    assert normalize_song_identity("One-Two (Live)") != normalize_song_identity("One Two")


def test_short_only_record_does_not_block_full_upload():
    db = HistoryDB(":memory:")
    for source in ("old", "new"):
        db.record_download(source, "url", "Song", "Artist", "", "channel", "url", "audio", "thumb")
    db.record_short_upload("old", "model", "short")
    assert db.get_duplicate_song_upload("new") is None
    db.close()
