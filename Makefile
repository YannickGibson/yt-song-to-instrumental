.PHONY: run test test-verbose sync

URL ?=
MODEL ?= htdemucs

run:
	uv run yt-instrumental $(URL) --model $(MODEL)

test:
	uv run pytest

test-verbose:
	uv run pytest -v -o log_cli=true -o log_cli_level=INFO

sync:
	uv sync --all-extras
