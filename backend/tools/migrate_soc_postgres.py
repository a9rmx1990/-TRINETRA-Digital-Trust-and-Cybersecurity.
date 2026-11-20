"""Copy a quiesced sandbox ledger to an empty Postgres schema."""

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from app.live.ledger import Ledger


TABLES = (
    "payments", "settled", "cases", "case_triage", "events", "restrictions", "challenges",
    "soc_jobs", "soc_tool_audit", "soc_proposals", "soc_holds", "soc_controls", "soc_feedback",
    "soc_watches", "soc_reports",
)
SEQUENCES = {"events", "soc_tool_audit", "soc_feedback"}


def migrate(source, destination):
    path = Path(source).resolve(strict=True)
    if not destination:
        raise ValueError("TRINETRA_DATABASE_URL is required")
    target = Ledger(None, database_url=destination)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as original:
        original.execute("BEGIN")
        present = {row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"payments", "cases", "events"} <= present:
            raise ValueError("The source does not contain a TRINETRA ledger")
        copied = {}
        with target.tx(write=True) as db:
            if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in TABLES):
                raise ValueError("Postgres target must be empty")
            for table in TABLES:
                if table not in present:
                    continue
                cursor = original.execute(f"SELECT * FROM {table}")
                columns = ",".join(field[0] for field in cursor.description)
                parameters = ",".join("?" for _ in cursor.description)
                if any(not column.isidentifier() for column in columns.split(",")):
                    raise ValueError(f"Invalid source schema for {table}")
                count = 0
                for row in cursor:
                    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({parameters})", tuple(row))
                    count += 1
                copied[table] = count
                actual = db.execute(f"SELECT count(*) AS total FROM {table}").fetchone()["total"]
                if actual != count:
                    raise RuntimeError(f"Count mismatch for {table}")
                if table in SEQUENCES:
                    db.execute(f"SELECT setval(pg_get_serial_sequence(?, 'seq'), "
                               f"COALESCE(MAX(seq), 1), MAX(seq) IS NOT NULL) FROM {table}", (table,))
    return copied


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Path to the SQLite ledger")
    args = parser.parse_args()
    for name, rows in migrate(args.source, os.getenv("TRINETRA_DATABASE_URL")).items():
        print(f"{name}: {rows}")
