#!/usr/bin/env bash
# Development: API with reload on :8000 and Vite on :5173 (proxying /api).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
env_args=()
if [[ -f "$ROOT/.env" ]]; then env_args=(--env-file "$ROOT/.env"); fi
(cd "$ROOT/backend" && python3 -m uvicorn app.main:app --reload --port 8000 "${env_args[@]}") &
API=$!
trap 'kill $API 2>/dev/null' EXIT
cd "$ROOT/frontend" && npm run dev
