"""Read-only MCP server over stdio (newline-delimited JSON-RPC 2.0).

    python tools/mcp_stdio.py --actor analyst.name

Exposes only the `analyst_read` role's case-scoped read tools. Every call is audited.
Run it on the host with database access; it never exposes write tools.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.soc.mcp import jsonrpc  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", required=True)
    args = ap.parse_args()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}), flush=True)
            continue
        if req.get("method") == "initialize":
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {
                "protocolVersion": "2024-11-05", "serverInfo": {"name": "trinetra-soc-read", "version": "2.0.0"},
                "capabilities": {"tools": {}}}}
        elif req.get("method", "").startswith("notifications/"):
            continue
        else:
            resp = jsonrpc("analyst_read", req, actor=f"stdio:{args.actor}")
        print(json.dumps(resp, default=str), flush=True)


if __name__ == "__main__":
    main()
