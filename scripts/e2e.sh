#!/usr/bin/env bash
# Browser walkthrough against an isolated backend with an empty database.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
PORT="${E2E_PORT:-8765}"
export E2E_ANALYST_PASSWORD="${E2E_ANALYST_PASSWORD:-e2e-analyst-password}"

(cd "$ROOT/frontend" && npm run build >/dev/null)
cd "$ROOT/backend"
TRINETRA_DATABASE_URL="sqlite:///$TMP/e2e.db" TRINETRA_DATA_DIR="$TMP" TRINETRA_ANALYST_WORKSPACE_PASSWORD="$E2E_ANALYST_PASSWORD" \
TRINETRA_FRONTEND_DIST="$ROOT/frontend/dist" TRINETRA_WORKERS=2 \
  python3 -m uvicorn tests.e2e_app:create_test_app --factory --host 127.0.0.1 --port "$PORT" --log-level warning &
PID=$!
trap 'kill $PID 2>/dev/null; rm -rf "$TMP"' EXIT
for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.2; done
cd "$ROOT/frontend"
E2E_BASE_URL="http://127.0.0.1:$PORT" npx playwright test "$@"
