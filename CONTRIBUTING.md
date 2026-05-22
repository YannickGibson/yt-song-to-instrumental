# Contributing

Thanks for your interest in improving yt-song-to-instrumental.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and
targets Python 3.12.

```bash
git clone https://github.com/YannickGibson/yt-song-to-instrumental.git
cd yt-song-to-instrumental
uv sync --extra dev          # unit tests only
uv sync --all-extras         # everything, including ML backends
```

[ffmpeg](https://ffmpeg.org/) must be installed and on your `PATH`.

## Running tests

```bash
uv run pytest                # unit tests (network/GPU tests are deselected)
uv run pytest -v -o log_cli=true -o log_cli_level=INFO
```

Tests marked `integration` require network or a GPU and are excluded by default.
All changes should keep the suite green.

## Conventions

These are enforced by review — please follow them:

1. **No hardcoded values.** All literals live in `yt_song_to_instrumental/constants.py`
   and are imported.
2. **No default values in `.get()` calls** — e.g. `config.get("key", "default")` is
   not allowed.
3. **Import at the top of the module.** The one exception is
   `yt_song_to_instrumental/separator/__init__.py`, which lazily imports ML backends
   because they pull in multi-GB dependencies.
4. New separator models implement the `SeparatorBackend` ABC in
   `yt_song_to_instrumental/separator/base.py` and document their memory
   requirements in both `README.md` and `CLAUDE.md`.
5. Audio/video processing shells out to ffmpeg — always pass arguments as a list,
   never via `shell=True`.

## Pull requests

- Keep changes focused; one logical change per PR.
- Add or update tests for the behavior you change.
- Make sure `uv run pytest` passes and CI is green.

## Configuration files

`.env`, `label.yml`, `client_secrets.json`, and `token.json` hold credentials or
private configuration and are gitignored. Never commit them. Use `.env.example` and
`label.yml.example` as templates.
