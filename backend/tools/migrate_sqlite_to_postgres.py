"""Copy a quiesced SQLite database into an empty PostgreSQL target and verify it.

    python tools/migrate_sqlite_to_postgres.py data/trinetra.db postgresql://user@host/db

Stop the API and workers first. The target must be empty (schema is created here).
Verification compares IDs, row counts, case states, event links and settlement totals,
then prints a rollback note. Exit code is non-zero on any mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Database  # noqa: E402

ORDER = ["owners", "accounts", "counterparties", "beneficiaries", "restrictions", "calls", "payments", "settlements",
         "challenges", "cases", "evidence", "case_events", "delivery_counter", "outbox", "proposals", "watches",
         "adjudications", "tool_audit", "command_results", "analyst_workspace_runs", "schema_meta"]
KEYS = {"case_events": "seq", "delivery_counter": "id", "command_results": "command_key", "schema_meta": "k"}


def has_analyst_runs(db: Database) -> bool:
    return db.dialect != "sqlite" or bool(db.read(lambda t: t.scalar(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'analyst_workspace_runs'"
    )))


def copy(src: Database, dst: Database) -> None:
    for table in ORDER:
        if table == "analyst_workspace_runs" and not has_analyst_runs(src):
            continue
        rows = src.read(lambda t: t.all(f"SELECT * FROM {table}"))
        if not rows:
            continue
        cols = list(rows[0].keys())
        target_cols = ["account_id" if table == "settlements" and c == "from_account_id" else c for c in cols]
        sql = f"INSERT INTO {table} ({', '.join(target_cols)}) VALUES ({', '.join('?' for _ in cols)})"
        if table in ("delivery_counter", "schema_meta"):
            k = KEYS[table]
            sql += f" ON CONFLICT ({k}) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != k)
        def _ins(t, rows=rows, sql=sql, cols=cols):
            for r in rows:
                t.execute(sql, [r[c] for c in cols])
        dst.write(_ins)
        print(f"copied {table}: {len(rows)}")
    dst.write(lambda t: t.execute("SELECT setval(pg_get_serial_sequence('case_events','seq'),"
                                  " COALESCE((SELECT MAX(seq) FROM case_events), 1))"))


def fingerprint(db: Database) -> dict:
    analyst_runs = has_analyst_runs(db)

    def _go(t):
        out = {}
        for table in ORDER:
            key = KEYS.get(table, "id")
            ids = [] if table == "analyst_workspace_runs" and not analyst_runs else [
                str(r[key]) for r in t.all(f"SELECT {key} FROM {table} ORDER BY {key}")
            ]
            out[f"{table}.count"] = len(ids)
            out[f"{table}.ids"] = hash(tuple(ids))
        out["case_states"] = sorted((r["id"], r["state"], r["version"]) for r in t.all("SELECT id, state, version FROM cases"))
        out["event_links"] = int(t.scalar("SELECT COUNT(*) FROM case_events e JOIN cases c ON c.id = e.case_id"))
        out["settlement_total"] = int(t.scalar("SELECT COALESCE(SUM(amount_minor), 0) FROM settlements"))
        out["payment_states"] = sorted((r["id"], r["state"]) for r in t.all("SELECT id, state FROM payments"))
        out["payment_directions"] = sorted((r["id"], r.get("direction", "outgoing")) for r in t.all("SELECT * FROM payments"))
        out["settlement_parties"] = sorted((r["payment_id"], r.get("account_id", r.get("from_account_id")), r["counterparty_id"])
                                           for r in t.all("SELECT * FROM settlements"))
        return out
    return db.read(_go)


def main(src_path: str, dst_url: str) -> int:
    src = Database(f"sqlite:///{src_path}")
    dst = Database(dst_url)
    if dst.dialect != "postgres":
        print("target must be PostgreSQL")
        return 2
    dst.migrate()
    if dst.read(lambda t: t.scalar("SELECT COUNT(*) FROM owners")):
        print("target is not empty; refusing to migrate")
        return 2
    copy(src, dst)
    dst.migrate()
    a, b = fingerprint(src), fingerprint(dst)
    bad = [k for k in a if a[k] != b[k]]
    for k in sorted(a):
        if k.endswith(".count") or k in ("event_links", "settlement_total"):
            print(f"{'OK ' if a[k] == b[k] else 'BAD'} {k}: {a[k]} -> {b[k]}")
    print("case states, payment states and id sets:", "match" if not bad else f"MISMATCH in {bad}")
    print("Rollback: the SQLite file is untouched. Point TRINETRA_DATABASE_URL back at it and restart.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
