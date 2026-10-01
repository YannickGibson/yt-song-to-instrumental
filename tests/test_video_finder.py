from unittest.mock import patch

import pytest

from yt_song_to_instrumental.video_detector import has_music_video_label
from yt_song_to_instrumental.video_finder import (
    _channel_video_cache,
    VideoChannelUnavailable,
    find_and_verify_music_video,
    get_channel_videos,
    is_trusted_music_video,
    search_channel_candidates,
)


@pytest.mark.parametrize("title", [
    "Artist - Track (Official Gaming Music Video)",
    "Artist - Track (Official ExampleGame Music Video)",
    "Artist - Track (Official Shooter2 Music Video)",
    "Artist - Track (Official Video) FPS Montage",
    "Artist - Track (Official Video) Gameplay",
    "Artist - Track (Music Video) Fan Edit",
    "Artist - Track [Official Video] (Unofficial)",
    "Artist - Track (AMV)",
    "Artist - Track (Official Visualizer)",
    "Artist - Track [Official Audio]",
    "Artist - Track (Lyric Video)",
    "Artist - Track (Reaction!)",
    "Artist - Track (Type Beat)",
    "Artist - Track (Guitar Cover)",
    "Artist - Track",
])
def test_moving_or_matching_audio_does_not_establish_music_video(title):
    assert not has_music_video_label(title)


@pytest.mark.parametrize("title", [
    "Artist - Track (Official Music Video)",
    "Artist - Track [OFFICIAL VIDEO]",
    "Artist - Track (Music Video)",
    "Artist - Track Official Music Video",
    "Artist - Track (Official MV)",
])
def test_explicit_music_video_labels(title):
    assert has_music_video_label(title)


@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_channel_requires_label_full_title_and_matching_duration(index):
    index.return_value = [
        {"id": "audio", "title": "Artist - Track (Official Audio)", "duration": 180},
        {"id": "game", "title": "Artist - Track (Official ExampleGame Music Video)", "duration": 180},
        {"id": "bare", "title": "Artist - Track", "duration": 180},
        {"id": "different", "title": "Artist - Other Track (Official Video)", "duration": 180},
        {"id": "long", "title": "Artist - Real Track (Official Video)", "duration": 600},
        {"id": "right", "title": "Artist - Real Track (Official Video)", "duration": 185},
    ]
    candidates = search_channel_candidates("channel", "Artist - Real Track", 180, artist="Artist")
    assert [entry["id"] for entry in candidates] == ["right"]


@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_same_artist_name_and_official_label_cannot_impersonate_channel(index):
    index.return_value = [{"id": "approved", "title": "Artist - Track (Official Video)"}]
    assert not is_trusted_music_video("fan-upload", "Artist - Track (Official Video)", "channel")
    assert is_trusted_music_video("approved", "Artist - Track (Official Video)", "channel")
    assert not is_trusted_music_video("approved", "Artist - Track (Gameplay)", "channel")
    assert not is_trusted_music_video("approved", "Artist - Track (Official Video)", None)


@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_explicit_request_can_screen_unlabeled_source_only_in_approved_channel(index):
    index.return_value = [{"id": "approved", "title": "Track"}]
    assert not is_trusted_music_video("approved", "Track", "channel")
    assert is_trusted_music_video("approved", "Track", "channel", requested_source=True)
    assert not is_trusted_music_video("unrelated", "Track", "channel", requested_source=True)
    assert not is_trusted_music_video("approved", "Track", None, requested_source=True)


@pytest.mark.parametrize("title", ["Track (Visualizer)", "Track (Gameplay)", "Track (Official Audio)", "Track (Fan Edit)", ""])
@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_requested_source_still_rejects_non_music_video_labels(index, title):
    index.return_value = [{"id": "approved", "title": title}]
    assert not is_trusted_music_video("approved", title, "channel", requested_source=True)
    index.assert_not_called()


@patch("yt_dlp.YoutubeDL")
def test_channel_tab_is_normalized_and_cached(ydl):
    _channel_video_cache.clear()
    extractor = ydl.return_value.__enter__.return_value
    extractor.extract_info.return_value = {"entries": [{"id": "official"}]}
    entries = get_channel_videos("https://www.youtube.com/@example/releases?view=0")
    assert entries == [{"id": "official"}]
    assert get_channel_videos("https://www.youtube.com/@example/videos") == entries
    extractor.extract_info.assert_called_once_with(
        "https://www.youtube.com/@example/videos", download=False,
    )
    _channel_video_cache.clear()


@patch("yt_dlp.YoutubeDL")
def test_failed_channel_index_is_retryable_and_never_searches_globally(ydl, tmp_path):
    _channel_video_cache.clear()
    extractor = ydl.return_value.__enter__.return_value
    extractor.extract_info.side_effect = [RuntimeError("temporarily unavailable"), {"entries": []}]
    with pytest.raises(VideoChannelUnavailable):
        find_and_verify_music_video("Artist", "Track", tmp_path,
                                    video_channel_url="https://www.youtube.com/@example")
    assert find_and_verify_music_video("Artist", "Track", tmp_path,
                                      video_channel_url="https://www.youtube.com/@example") == (None, 0.0, None)
    assert extractor.extract_info.call_count == 2
    assert all(call.args[0] == "https://www.youtube.com/@example/videos"
               for call in extractor.extract_info.call_args_list)
    _channel_video_cache.clear()


@patch("yt_dlp.YoutubeDL")
def test_missing_channel_cannot_start_global_search(ydl, tmp_path):
    assert find_and_verify_music_video("Artist", "Track", tmp_path) == (None, 0.0, None)
    ydl.assert_not_called()


@patch("yt_song_to_instrumental.video_finder.detect_if_music_video")
@patch("yt_song_to_instrumental.video_finder.download_source_video")
@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_success_requires_approved_source_and_structural_checks(index, download, detect, tmp_path):
    index.return_value = [{"id": "official", "title": "Artist - Track (Official Video)", "duration": 180}]
    video = tmp_path / "official.mp4"
    video.touch()
    download.return_value = video
    detect.return_value = (True, 15.4)
    result = find_and_verify_music_video("Artist", "Track", tmp_path, 180,
                                         video_channel_url="https://www.youtube.com/@example")
    assert result == (video, 15.4, "https://www.youtube.com/watch?v=official")
    assert detect.call_args.kwargs["video_title"] == "Artist - Track (Official Video)"


@patch("yt_song_to_instrumental.video_finder.detect_if_music_video")
@patch("yt_song_to_instrumental.video_finder.download_source_video")
@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_failed_structure_is_cleaned_and_next_channel_candidate_is_tried(index, download, detect, tmp_path):
    index.return_value = [
        {"id": "loop", "title": "Artist - Track (Official Video)"},
        {"id": "real", "title": "Artist - Track (Official Music Video)"},
    ]
    loop, real = tmp_path / "loop.mp4", tmp_path / "real.mp4"
    loop.touch()
    real.touch()
    download.side_effect = [loop, real]
    detect.side_effect = [(False, 0.04), (True, 25.0)]
    result = find_and_verify_music_video("Artist", "Track", tmp_path,
                                         video_channel_url="https://www.youtube.com/@example")
    assert result[0] == real
    assert not loop.exists()


@patch("yt_song_to_instrumental.video_finder.download_source_video")
@patch("yt_song_to_instrumental.video_finder.get_channel_videos")
def test_channel_gameplay_never_reaches_downloader(index, download, tmp_path):
    index.return_value = [{"id": "game", "title": "Artist - Track (Official ExampleGame Music Video)"}]
    assert find_and_verify_music_video("Artist", "Track", tmp_path,
                                       video_channel_url="channel") == (None, 0.0, None)
    download.assert_not_called()
