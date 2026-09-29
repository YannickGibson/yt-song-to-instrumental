# yt-song-to-instrumental

[![CI](https://github.com/YannickGibson/yt-song-to-instrumental/actions/workflows/ci.yml/badge.svg)](https://github.com/YannickGibson/yt-song-to-instrumental/actions/workflows/ci.yml)

Download songs from YouTube, extract instrumentals using AI source separation, and auto-upload them to a dedicated YouTube instrumentals channel. Built for music labels that own the rights to their artists' catalogs.

## Features

- **Switchable ML models** — HTDemucs, UVR-MDX-NET Inst_HQ_4, or the MPS instrumental preset
- **Automated YouTube uploads** — OAuth2, resumable uploads, privacy controls
- **Playlist management** — auto-creates per-artist and per-album playlists
- **Shorts playlist** — existing and future Shorts join the shared `shorts` playlist
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

| Model | ID | RAM guidance | GPU Required | GPU VRAM | Notes |
|-------|----|---------|-------------|----------|-------|
| HTDemucs | `htdemucs` | 4 GB | No (recommended) | 2 GB+ | 4-stem demucs v4. Measured ~7x realtime on Pi 4. |
| UVR-MDX-NET Inst_HQ_4 | `inst_hq_4` | 3 GB | No (recommended) | 1 GB+ | ONNX via `audio-separator`. 2-stem vocals/instrumental. Cleaner vocal removal but ~12x realtime on Pi 4 — best on x86/GPU. |
| MelBand RoFormer INSTV7N | `mel_gabox_instv7n` | Observed worker peak ~3.5 GiB; system minimum unverified | MPS required | Shared system memory | Native FP16 with protected FP32 parameters, overlap 4, model-default segments, and two CPU threads. |

The MPS backend requires `audio-separator[cpu]==0.47.0`, `torch==2.14.0`, and
`demucs==4.1.0` in a separate environment. The legacy CPU extras and lockfile
have incompatible version constraints and must not synchronize this environment.
Invoke its installed executable directly. Set
`AUDIO_SEPARATOR_MODEL_DIR` to a persistent checkpoint cache if desired.
Published source videos are recognized across model changes, and pending Shorts
retain their historical model and original upload association.

#### INSTV7N memory requirements

Measurements for `mel_gabox_instv7n` on an MPS device, using native FP16 with
protected FP32 parameters, batch size 1, overlap 4, model-default segments,
and two CPU threads:

| Measurement | Observed usage | Scope |
|-------------|----------------|-------|
| Worker physical footprint | ~3.5 GiB peak | Process-lifetime peak reported by `vmmap -summary` for a running worker |
| Process resident memory (RSS) | ~2.03 GiB peak in each run | Two separate full-song runs, approximately 163 and 232 seconds of audio |
| MPS driver allocations | 2.62–3.62 GiB sampled maxima | Same two full-song runs, sampled every 0.5 seconds |

These counters overlap in unified memory; **do not add them together**. The
[MPS driver counter](https://docs.pytorch.org/docs/2.14/generated/torch.mps.driver_allocated_memory.html)
includes cached allocations and framework allocations. Sampling can miss brief
peaks, and the worker footprint excludes separate audio/video subprocesses.

The backend's **8 GB budget is a planning estimate**. Minimum system RAM and
compatibility with an 8 GB system remain unverified. Allow additional headroom
for the operating system, audio/video processing, and other applications.
Run one separation worker at a time; longer inputs or different batch/segment
settings require separate validation. This backend requires **MPS** and uses
shared system memory rather than a separate VRAM budget.

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

Playlist additions continue while older ordering issues are repaired separately.
Failed memberships persist in SQLite and retry without uploading videos again;
one unavailable playlist does not block the other destinations. Run
`yt-instrumental --retry-playlists` to retry queued memberships and backfill
recorded Shorts without starting audio processing or video uploads. Recovery
shares the API budget with the worker and resumes on a later run after quota resets.

Once `label.yml` is configured, the everyday command takes **no arguments**:

```bash
uv run yt-instrumental
```

This scans every channel and playlist under `sources:` in `label.yml`, downloads new tracks, extracts instrumentals, and uploads them. Every download, separation, and upload is recorded in a local SQLite database (`data/history.db`), so re-running only picks up what's new — nothing is processed or uploaded twice.

Set `upload_interval_seconds: 1200` in `label.yml` to leave at least 20 minutes
after each completed upload before starting the next. Instrumentals, Shorts,
and priority requests share this interval. The worker checks durable upload
history, so restarts preserve the remaining wait and downtime creates no burst
of missed uploads. Separation and rendering can finish while the next upload
waits. An omitted value or `0` disables pacing; use one worker per history DB.

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

### Priority instrumental requests

Queue a requested song ahead of normally discovered tracks without starting a
second pipeline process:

```bash
uv run yt-instrumental --enqueue-priority "https://www.youtube.com/watch?v=VIDEO_ID"
uv run yt-instrumental --enqueue-priority "https://www.youtube.com/watch?v=VIDEO_ID" \
  --priority-short --priority-short-start 35
uv run yt-instrumental --list-priority
```

The queue is stored in `data/history.db`. The newest request is position one.
The managed worker checks the queue before each normal track, finishes any track
already in progress, and then drains requested songs newest-first. Each request
uses the same download, separation, upload, playlist, and history code as a
normal source item.

`--priority-short` requires the requested track's long-form instrumental and a
verified music-video Short, in that order, even when routine Shorts are paused.
`--priority-short-start` selects the Short's synchronized audio/video content
offset in seconds (defaults to 10% of the video duration). The request
remains incomplete until both uploads are recorded in SQLite.

Python callers can use the same enqueue operation directly:

```python
from yt_song_to_instrumental.priority import enqueue_priority_request

request = enqueue_priority_request(
    "https://www.youtube.com/watch?v=VIDEO_ID",
    upload_short=True,
    short_start_seconds=35.0,
)
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

- **`upload_short_if_music_video: true`**: Requires an explicit music-video label, such as `(Official Video)` or `(Music Video)`, and membership in the configured `video_channel_url`. Without that setting, only the original release channel is trusted. This applies to both direct sources and alternate videos. An uploader name or the word “official” alone is insufficient; there is no global-search fallback to unrelated channels. Gaming, fan-edit, audio and visualizer labels are rejected, followed by motion, repetition and scene-diversity checks. Alternate videos must match the full song title and duration. Tracks without a qualifying video are skipped.
- **Source limitations**: These conservative publisher and metadata checks favor avoiding unsuitable uploads. They can skip genuine videos with unusual titles or videos published by a director; configure the approved video channel explicitly. Motion and audio matching cannot prove that footage depicts a music video, so misleadingly labeled content on an approved channel may still need review.
- **`upload_short: true`**: Requests Shorts for processed tracks, still subject to the same source validation; it cannot bypass visualizer rejection.
- **Audio/Video Sync**: Matches the original release audio against the music-video soundtrack, then applies the instrumental's silence-trim offset. Intros and earlier cuts can have different video/audio start times. Every second of the selected 20-second passage must agree, so pauses, edits, tempo drift, unrelated audio, and ambiguous matches cannot silently produce an out-of-sync upload. Automatic selection can try nearby continuous passages; an explicit `--priority-short-start` keeps the exact requested instrumental offset. Missing or uncertain audio matches record a retryable `audio_alignment_failed` status and do not upload a Short. Analysis is bounded to recordings of at most 15 minutes. Existing published Shorts remain unchanged.
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


Short teaser titles end with the resolved primary artist in square brackets:
`Song (Instrumental Teaser) [Artist]`. The suffix is retained within the YouTube
100-character title limit. Already-posted videos are not retitled automatically.

### Resumable playlist repair

The managed worker repairs playlists at startup and between tracks. Repair is
bounded to 75 attempted moves and 4,000 general API quota units per Pacific day.
Normal general-API calls have a separate 5,500-unit ceiling, leaving 500 units
of safety headroom against the documented default allocation. Upload and search
initiations are counted in their dedicated buckets (90 calls each). These are
conservative local limits, not a claim about the project's actual allocation.
All managed callers must use the same `QuotaLedger` and request builder; external
clients are not observable by this local ledger. API quota errors pause repairs.

`data/youtube-quota.db`, beside the OAuth token's directory, holds daily counters,
repair progress and write intents. Playlist writes are serialized across clients.
A fresh live read precedes each resumed plan, and changed playlists are read back
after each slice. Ambiguous writes are never retried using stale positions.
Unknown source items are preserved at durable anchor positions, not deleted or
assigned invented release dates. Playlist-item IDs, not video IDs, identify moves
so existing duplicates and membership remain intact.

The same positioned-insert guard checks known release order and queues additions
to unrepaired playlists. Repairs reserve quota even when uploads run continuously.
Keep the quota database private and persistent across restarts.
