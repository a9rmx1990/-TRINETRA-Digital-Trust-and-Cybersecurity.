#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
if [[ -f ../.env ]]; then
    set -a
    source ../.env
    set +a
fi
export PYTHONPATH=.
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
