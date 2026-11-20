#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../.."
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi
export PYTHONPATH=backend
exec backend/.venv/bin/python backend/tools/evaluate_classifiers.py "$@"
