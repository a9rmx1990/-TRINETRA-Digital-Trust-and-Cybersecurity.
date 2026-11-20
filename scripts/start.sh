#!/usr/bin/env bash
# Quick start: build the UI and serve both workspaces from one process on SQLite.
#   Customer workspace: http://127.0.0.1:8000/      SOC workspace: http://127.0.0.1:8000/soc
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/frontend" && { [ -d node_modules ] || npm ci; } && npm run build)
cd "$ROOT/backend"
export TRINETRA_FRONTEND_DIST="$ROOT/frontend/dist"
echo "Analyst passcode: see backend/data/analyst-passcode.txt (or set TRINETRA_ANALYST_PASSCODE)"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
