#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

if [ -n "${YT_WORKER_PYTHON:-}" ]; then
    exec "$YT_WORKER_PYTHON" -m yt_song_to_instrumental.cli \
        --model "${YT_SEPARATOR_MODEL:-htdemucs}" \
        --upload-timeout "${YT_UPLOAD_TIMEOUT_MINUTES:-120}"
fi
exec "${UV_BIN:-uv}" run yt-instrumental \
    --model "${YT_SEPARATOR_MODEL:-htdemucs}" \
    --upload-timeout "${YT_UPLOAD_TIMEOUT_MINUTES:-120}"
