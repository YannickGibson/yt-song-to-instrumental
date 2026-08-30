# yt-song-to-instrumental

[![CI](https://github.com/YannickGibson/yt-song-to-instrumental/actions/workflows/ci.yml/badge.svg)](https://github.com/YannickGibson/yt-song-to-instrumental/actions/workflows/ci.yml)

Download songs from YouTube, extract instrumentals using AI source separation, and auto-upload them to a dedicated YouTube instrumentals channel. Built for music labels that own the rights to their artists' catalogs.

## Features

- **Switchable ML models** — HTDemucs, UVR-MDX-NET Inst_HQ_4, or add your own
- **Automated YouTube uploads** — OAuth2, resumable uploads, privacy controls
- **Playlist management** — auto-creates per-artist and per-album playlists
- **Configurable templates** — video titles, descriptions, and playlist names use `<tag>` syntax
- **Duplicate detection** — SQLite tracking DB prevents re-processing/re-uploading
- **Quality gate** — checks for silence and minimum duration before upload
- **Thumbnail-as-video** — renders the original video's highest-res thumbnail as a static image video

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [ffmpeg](https://ffmpeg.org/) (audio/video processing)
- Google Cloud project with YouTube Data API v3 enabled

### Model Requirements

| Model | ID | Min RAM | GPU Required | GPU VRAM | Notes |
|-------|----|---------|-------------|----------|-------|
| HTDemucs | `htdemucs` | 4 GB | No (recommended) | 2 GB+ | 4-stem demucs v4. Measured ~7x realtime on Pi 4. |
| UVR-MDX-NET Inst_HQ_4 | `inst_hq_4` | 3 GB | No (recommended) | 1 GB+ | ONNX via `audio-separator`. 2-stem vocals/instrumental. Cleaner vocal removal but ~12x realtime on Pi 4 — best on x86/GPU. |

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YannickGibson/yt-song-to-instrumental.git
cd yt-song-to-instrumental
uv sync --extra dev
```

To install with a specific model backend:

```bash
uv sync --all-extras       # Everything (recommended)
```

Both backends are installed by `--all-extras`. The `audio-separator` package brings its own ONNX Runtime and downloads model weights on first use.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required `.env` values:

| Variable | Description |
|----------|-------------|
| `YOUTUBE_CLIENT_SECRETS_FILE` | Path to `client_secrets.json` from Google Cloud Console |
| `YOUTUBE_TOKEN_FILE` | Where to cache the OAuth token (default: `token.json`) |
| `YOUTUBE_CHANNEL_ID` | Target YouTube channel ID for uploads |
| `SEPARATOR_MODEL` | (Optional) Default model when not set in `label.yml` — `htdemucs` or `inst_hq_4` |

### 3. Configure label

```bash
cp label.yml.example label.yml
```

Edit `label.yml` with your label's name, metadata templates, and — most importantly — the `sources:` list: the YouTube / YouTube Music channels and playlists to scan. This is what the tool processes when run with no URL.

### 4. Google Cloud setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Desktop application)
4. Download `client_secrets.json` to the project root
5. On first run, a browser will open for OAuth consent

## Usage

Once `label.yml` is configured, the everyday command takes **no arguments**:

```bash
uv run yt-instrumental
```

This scans every channel and playlist under `sources:` in `label.yml`, downloads new tracks, extracts instrumentals, and uploads them. Every download, separation, and upload is recorded in a local SQLite database (`data/history.db`), so re-running only picks up what's new — nothing is processed or uploaded twice.

### Scheduled runs

Because re-runs are safe and incremental, the tool is meant to run on a schedule. Add a cron entry with `crontab -e`:

```cron
# Every 6 hours: pick up new tracks from the sources in label.yml
0 */6 * * * cd /path/to/yt-song-to-instrumental && uv run yt-instrumental >> logs/cron.log 2>&1
```

### Processing a one-off URL

To process a specific video, playlist, or channel without touching `sources:`, pass a URL directly:

```bash
uv run yt-instrumental https://youtube.com/watch?v=VIDEO_ID
uv run yt-instrumental https://youtube.com/playlist?list=PLAYLIST_ID
uv run yt-instrumental https://youtube.com/@ChannelName
```

### Common options

```bash
uv run yt-instrumental --dry-run       # show what would be processed, then exit
uv run yt-instrumental --skip-upload   # separate only, don't upload
uv run yt-instrumental --shorts-only   # process/upload YouTube Shorts only (skip full-length videos)
uv run yt-instrumental --upload-short  # force uploading Shorts for all tracks in this run
uv run yt-instrumental --upload-short-if-music-video # upload Shorts only if detected as music video
uv run yt-instrumental --no-upload-short # disable Shorts uploads for this run
uv run yt-instrumental --model inst_hq_4  # override label.yml's default_model
uv run yt-instrumental --sync-channel  # push channel name/description from label.yml
uv run yt-instrumental --list-models   # list separation models, then exit
```

Run `uv run yt-instrumental --help` for the full list — privacy, artist/album overrides, date filtering, upload timeout, and verbose logging.

## Template Tags

Used in `label.yml` for video titles, descriptions, and playlist names:

| Tag | Description |
|-----|-------------|
| `<artist-name>` | Artist/performer name |
| `<track-title>` | Original track title |
| `<album-name>` | Album name |
| `<original-url>` | URL of the original YouTube video |
| `<original-channel-url>` | URL of the original YouTube channel |
| `<model-name>` | Separation model used (e.g. HTDemucs) |
| `<label-name>` | Label name from `label.yml` |
| `<artist-tag>` | Artist name sanitized for hashtag use |
| `<full-video-url>` | URL of the uploaded long-form instrumental video (for Shorts descriptions) |

## YouTube Shorts Generation

The pipeline can automatically generate and upload 20-second vertical YouTube Shorts teasers (1080×1920 with 20% top/bottom black bars) for instrumental tracks:

- **`upload_short_if_music_video: true`**: Automatically checks whether the source YouTube video is an active music video using low-overhead frame difference motion detection, skipping static album covers and simple visualizers.
- **`upload_short: true`**: Uploads Shorts for all processed tracks unconditionally.
- **Audio/Video Sync**: Automatically aligns video slicing with the instrumental start trim offset.
- **Titles & Descriptions**: Automatically formats titles as `<song name> (Instrumental)` and inserts the link to the full instrumental video.

## Playlist Management

The tool automatically manages two tiers of playlists:

- **Per-artist playlist**: e.g. `"Riku Vex (Instrumentals)"` — all instrumentals by that artist
- **Per-album playlist**: e.g. `"Riku Vex — Quiet Hours (Instrumentals)"` — only tracks from that album

Playlist names are configurable in `label.yml`. Playlists are created on YouTube if they don't exist and cached locally.

## Adding New Models

1. Create `yt_song_to_instrumental/separator/your_model_backend.py`
2. Implement the `SeparatorBackend` ABC from `separator/base.py`
3. Register it in `separator/__init__.py` (add to the `get_separator()` factory)
4. Add the model ID to `constants.py` (`AVAILABLE_MODELS`, `MODEL_DISPLAY_NAMES`)
5. Document memory requirements in `CLAUDE.md` and this README

## Development

```bash
# Run tests
uv run pytest

# Run tests with verbose output
uv run pytest -v -o log_cli=true -o log_cli_level=INFO

# Sync all deps including dev
uv sync --all-extras
```

## Disclaimer

This tool is intended for use by rights holders — music labels and artists processing
catalogs they own or are licensed to distribute.

Downloading content from YouTube may violate [YouTube's Terms of Service](https://www.youtube.com/t/terms),
and re-uploading audio you do not own may infringe copyright. You are solely
responsible for ensuring you have the necessary rights and for complying with all
applicable laws and platform terms in your jurisdiction. The authors accept no
liability for misuse.

This project is not affiliated with, endorsed by, or sponsored by YouTube or Google.

## License

MIT — see [LICENSE](LICENSE).
