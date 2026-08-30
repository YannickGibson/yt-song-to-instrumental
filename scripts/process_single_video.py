import sys
import logging
from pathlib import Path

from yt_song_to_instrumental.config import AppConfig, YouTubeConfig, load_label_config
from yt_song_to_instrumental.constants import MODEL_DISPLAY_NAMES
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.pipeline import _RunContext, _separate_track, _upload_track, PipelineReport
from yt_song_to_instrumental.separator import get_separator
from yt_song_to_instrumental.uploader import authenticate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

video_id = sys.argv[1] if len(sys.argv) > 1 else "RMzb9uyK8Q8"

app_config = AppConfig()
label_config = load_label_config()
yt_config = YouTubeConfig()

history = HistoryDB(app_config.db_path)
dl = history.get_download(video_id)
if not dl:
    print(f"Error: video_id {video_id} not found in downloads DB")
    sys.exit(1)

service = authenticate(yt_config.client_secrets_file, yt_config.token_file)

model = "htdemucs"
ctx = _RunContext(
    service=service,
    history=history,
    label_config=label_config,
    separator=get_separator(model),
    model=model,
    display_name=MODEL_DISPLAY_NAMES.get(model, model),
    privacy=app_config.default_privacy,
    tmp_dir=Path(app_config.tmp_dir),
    output_dir=Path(app_config.output_dir),
    upload_max_wait_seconds=None,
    cleanup_after_upload=True,
    trim_silence=label_config.trim_silence,
    trim_silence_threshold_db=label_config.trim_silence_threshold_db,
    preserve_original_video_title=False,
)

report = PipelineReport()

print(f"Starting targeted processing for video_id={video_id} ({dl.artist} - {dl.title})")
if _separate_track(dl, dl.artist, ctx, report):
    _upload_track(dl, dl.artist, dl.album, ctx, report)

print("\n--- Single Video Pipeline Report ---")
print(f"Separated: {report.separated}")
print(f"Uploaded:  {report.uploaded}")
print(f"Failed:    {report.failed}")
for t in report.tracks:
    print(f"Track: {t.title} | Status: {t.status} | YouTube ID: {t.youtube_upload_id}")

history.close()
