#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

exec /home/pi/.local/bin/uv run yt-instrumental \
    --model htdemucs \
    --upload-timeout 120
