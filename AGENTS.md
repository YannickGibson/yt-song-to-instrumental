# yt-song-to-instrumental

## Dev commands
- Install deps: `uv sync --all-extras`
- Run tests: `uv run pytest`
- Run tests verbose: `uv run pytest -v -o log_cli=true -o log_cli_level=INFO`
- Run tool: `uv run yt-instrumental <url> --model htdemucs`

## Project layout
- Source code lives in `yt_song_to_instrumental/`
- Tests live in `tests/`

## Rules
1. No hardcoded values. All literals go in `yt_song_to_instrumental/constants.py` and are imported.
2. No default values in `.get()` calls (e.g., `config.get("key", "default")` is forbidden).
3. Always import at top of module. EXCEPTION: `yt_song_to_instrumental/separator/__init__.py` uses lazy imports for ML backends because they pull in multi-GB dependencies.
4. Use pytest. Run with: `uv run pytest`
5. The `.env` file contains YouTube OAuth credentials. Never commit it.
6. `label.yml` contains label-specific config. Never commit it. `label.yml.example` is the public template.
7. All audio processing uses ffmpeg via subprocess — ensure paths are quoted/escaped.
8. Separator models use a strategy pattern (ABC in `yt_song_to_instrumental/separator/base.py`). New models implement that ABC.
9. Default separator: HTDemucs v4 (demucs 4.0.1).
10. It is possible that there will be multiple agents running at one time, keep that in mind.
11. Do not use public artists or company names in the tests or anywhere in the non gitignored parts of the project.
12. Add requested songs with `enqueue_priority_request()` or `--enqueue-priority`; never start a second pipeline alongside `yt-instrumental.service`. After enqueueing a user-requested song, restart the user service with `systemctl --user restart --no-block yt-instrumental.service` so the updated worker claims it immediately, then verify the request is claimed from the service output.
13. Priority requests persist in the `priority_requests` table and must run through the normal pipeline so `downloads`, `separations`, `uploads`, and playlists remain authoritative.
14. A priority request may take the next safe slot between tracks, but must never interrupt separation, rendering, or upload in progress.
15. Preserve crash and power-loss recovery: commit a stage to SQLite only after its durable output is complete, leave incomplete normal stages eligible for retry, and requeue priority requests left in `processing` when the next worker starts.
16. Add recovery tests whenever changing stage persistence, priority claim/completion behavior, or shutdown handling.
17. Code changes are not complete until the full local test suite passes and the corresponding GitHub Actions CI run finishes successfully. Never treat local tests alone as final verification.
18. This is a public repository. Never commit credentials, tokens, `.env`, `label.yml`, database/media artifacts, or artist/label-specific names and configuration. Keep tests, fixtures, docs, branch names, commit messages, and PR text generic.

## Daily maintenance
- Check the user service and timer, recent failures, SQLite queue/stage state, disk/memory headroom, and whether work is making progress.
- Confirm playlist ordering follows source release order, and confirm eligible music videos receive Shorts. A lack of new Shorts is healthy only when there are no eligible unuploaded songs.
- Check the latest GitHub Actions run and investigate or fix failures.
- Before every public push, inspect the tracked file list and staged diff for secrets, private configuration, and artist/label-specific data.
- Do not run a second pipeline. Restart a failed/stuck service only after inspecting its state; interrupted stages must remain recoverable.

## Playlist architecture & single-track release suppression
- Single-track releases (singles) must NEVER generate album playlists. They only route to artist & channel playlists.
- `album_is_self_titled_single` normalizes and strips parentheticals (features, `(Solo)`, `(Demo Speed)`), suffixes (`- Single`, `- EP`), and unparenthesized features when checking if an album tag is just a single.
- Official multi-track releases are verified via `AlbumIndex` discography catalog size (`track_count > 1`).
- Per-source `create_album_playlists: false` (defaults to `true`) can explicitly suppress album playlists for curator/archive channels in `label.yml`.

## Scripts directory policy
- `scripts/` must ONLY contain operational automation and systemd scripts (`daily-run.sh`, `backup-history-db.sh`, `notify-failure.sh`).
- Never commit ad-hoc or one-time fix/migration scripts to the repository.

## Model memory requirements
When adding a new separation model backend, document its requirements here AND in README.md:

| Model | Min RAM | GPU Required | GPU VRAM | Notes |
|-------|---------|-------------|----------|-------|
| HTDemucs | 4 GB | No (but recommended) | 2 GB+ | 4-stem demucs v4. Measured ~7x realtime on Pi 4 (4 GB). |
| Inst_HQ_4 | 3 GB | No (but recommended) | 1 GB+ | UVR-MDX-NET via ONNX (audio-separator). 2-stem vocals/instrumental. Cleaner vocal removal than HTDemucs but ~12x realtime on Pi 4 — best on x86/GPU. |

## CI & Test dependencies
- When running tests in CI (`.github/workflows/ci.yml`) or in fresh environments, install dependencies with `uv sync --extra dev --extra all-models` (or `uv sync --all-extras`).
- `tests/test_separator.py` imports separator backend modules directly (e.g. `inst_hq_4_backend.py`), which loads `audio_separator` requiring `onnxruntime` at import time. Omitting `onnxruntime` will cause CI test collection to fail with `ModuleNotFoundError: No module named 'onnxruntime'`.
