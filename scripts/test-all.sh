#!/usr/bin/env bash
# Runs every automated check. Set TRINETRA_TEST_PG_URL to include live PostgreSQL.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== backend unit, integration, concurrency =="
(cd "$ROOT/backend" && python3 -m pytest tests -q -rs)
echo "== frontend typecheck, unit, build =="
(cd "$ROOT/frontend" && npm run typecheck && npm test && npm run build)
echo "== browser walkthrough and accessibility =="
"$ROOT/scripts/e2e.sh"
