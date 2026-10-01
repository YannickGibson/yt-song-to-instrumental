#!/usr/bin/env bash
# Provision only the independent MPS environment; service admission is separate.
set -euo pipefail
cd "$(dirname "$0")/.."
worker_env="${YT_WORKER_ENV:-$PWD/.venv-mac}"
if [ -e .venv ] && [ -e "$worker_env" ] && [ .venv -ef "$worker_env" ]; then
    echo 'Development and worker environments must be separate.' >&2
    exit 1
fi
if [ ! -e "$worker_env/bin/python" ]; then
    uv venv --python 3.12 "$worker_env"
fi
uv pip install --python "$worker_env/bin/python" -r requirements-mac-worker.txt
