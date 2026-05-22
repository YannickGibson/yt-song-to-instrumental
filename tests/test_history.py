from yt_song_to_instrumental.history import HistoryDB


def make_db() -> HistoryDB:
    return HistoryDB(db_path=":memory:")


def _record_sample_download(db: HistoryDB, video_id: str = "abc123") -> None:
    db.record_download(
        video_id=video_id,
        url=f"https://youtube.com/watch?v={video_id}",
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        channel_name="Test Channel",
        channel_url="https://youtube.com/c/testchannel",
        audio_path=f"/tmp/{video_id}.wav",
        thumbnail_path=f"/tmp/{video_id}.jpg",
    )


class TestDownloads:
    def test_is_downloaded_false_initially(self):
        db = make_db()
        assert db.is_downloaded("abc123") is False

    def test_record_and_check_download(self):
        db = make_db()
        _record_sample_download(db)
        assert db.is_downloaded("abc123") is True

    def test_get_download(self):
        db = make_db()
        _record_sample_download(db)
        record = db.get_download("abc123")
        assert record is not None
        assert record.title == "Test Song"
        assert record.artist == "Test Artist"
        assert record.album == "Test Album"
        assert record.channel_name == "Test Channel"

    def test_get_download_nonexistent(self):
        db = make_db()
        assert db.get_download("nonexistent") is None

    def test_get_all_downloads(self):
        db = make_db()
        _record_sample_download(db, "vid1")
        _record_sample_download(db, "vid2")
        records = db.get_all_downloads()
        assert len(records) == 2

    def test_record_download_upsert(self):
        db = make_db()
        _record_sample_download(db)
        db.record_download(
            video_id="abc123",
            url="https://youtube.com/watch?v=abc123",
            title="Updated Title",
            artist="Test Artist",
            album="Test Album",
            channel_name="Test Channel",
            channel_url="https://youtube.com/c/testchannel",
            audio_path="/tmp/abc123.wav",
            thumbnail_path="/tmp/abc123.jpg",
        )
        record = db.get_download("abc123")
        assert record.title == "Updated Title"


class TestSeparations:
    def test_is_separated_false_initially(self):
        db = make_db()
        assert db.is_separated("abc123", "htdemucs") is False

    def test_record_and_check_separation(self):
        db = make_db()
        db.record_separation("abc123", "htdemucs", "/tmp/instrumental.wav", True)
        assert db.is_separated("abc123", "htdemucs") is True
        assert db.is_separated("abc123", "mdxnet") is False

    def test_get_unprocessed(self):
        db = make_db()
        _record_sample_download(db, "vid1")
        _record_sample_download(db, "vid2")
        _record_sample_download(db, "vid3")
        db.record_separation("vid1", "htdemucs", "/tmp/v1.wav", True)

        unprocessed = db.get_unprocessed("htdemucs")
        ids = [r.video_id for r in unprocessed]
        assert "vid1" not in ids
        assert "vid2" in ids
        assert "vid3" in ids

    def test_get_unprocessed_different_model(self):
        db = make_db()
        _record_sample_download(db, "vid1")
        db.record_separation("vid1", "htdemucs", "/tmp/v1.wav", True)

        unprocessed_mdx = db.get_unprocessed("mdxnet")
        assert len(unprocessed_mdx) == 1
        assert unprocessed_mdx[0].video_id == "vid1"


class TestUploads:
    def test_is_uploaded_false_initially(self):
        db = make_db()
        assert db.is_uploaded("abc123", "htdemucs") is False

    def test_record_and_check_upload(self):
        db = make_db()
        db.record_upload("abc123", "htdemucs", "yt_upload_id_1", "unlisted")
        assert db.is_uploaded("abc123", "htdemucs") is True
        assert db.is_uploaded("abc123", "mdxnet") is False

    def test_get_pending_upload(self):
        db = make_db()
        _record_sample_download(db, "vid1")
        _record_sample_download(db, "vid2")
        db.record_separation("vid1", "htdemucs", "/tmp/v1.wav", True)
        db.record_separation("vid2", "htdemucs", "/tmp/v2.wav", True)
        db.record_upload("vid1", "htdemucs", "yt_1", "unlisted")

        pending = db.get_pending_upload("htdemucs")
        assert len(pending) == 1
        assert pending[0].video_id == "vid2"

    def test_get_pending_upload_excludes_failed_qa(self):
        db = make_db()
        _record_sample_download(db, "vid1")
        db.record_separation("vid1", "htdemucs", "/tmp/v1.wav", False)

        pending = db.get_pending_upload("htdemucs")
        assert len(pending) == 0


class TestPlaylists:
    def test_get_playlist_nonexistent(self):
        db = make_db()
        assert db.get_playlist("artist", "Riku Vex") is None

    def test_record_and_get_artist_playlist(self):
        db = make_db()
        db.record_playlist("artist", "Riku Vex", None, "PLabc123")
        record = db.get_playlist("artist", "Riku Vex")
        assert record is not None
        assert record.youtube_playlist_id == "PLabc123"
        assert record.album is None

    def test_record_and_get_album_playlist(self):
        db = make_db()
        db.record_playlist("album", "Riku Vex", "Quiet Hours", "PLdef456")
        record = db.get_playlist("album", "Riku Vex", "Quiet Hours")
        assert record is not None
        assert record.youtube_playlist_id == "PLdef456"
        assert record.album == "Quiet Hours"

    def test_artist_and_album_playlists_separate(self):
        db = make_db()
        db.record_playlist("artist", "Riku Vex", None, "PLartist")
        db.record_playlist("album", "Riku Vex", "Quiet Hours", "PLalbum")
        assert db.get_playlist("artist", "Riku Vex").youtube_playlist_id == "PLartist"
        assert db.get_playlist("album", "Riku Vex", "Quiet Hours").youtube_playlist_id == "PLalbum"
