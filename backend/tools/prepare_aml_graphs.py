"""Convert IBM AMLWorld transfers into point-in-time TRINETRA graph examples."""

import argparse
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app.live.graph import analyze, context


def transactions(stream):
    reader = csv.reader(stream)
    header = next(reader, [])
    if (header[:5] != ["Timestamp", "From Bank", "Account", "To Bank", "Account"]
            and header[:5] != ["Timestamp", "From Bank", "Account", "To Bank", "Account.1"]):
        raise ValueError(f"Unexpected sender/recipient columns: {header[:5]}")
    label_at = header.index("Is Laundering")
    time_cache = {}
    for index, row in enumerate(reader):
        timestamp = row[0]
        if timestamp not in time_cache:
            if len(time_cache) > 8192:
                time_cache.clear()
            time_cache[timestamp] = datetime.strptime(timestamp, "%Y/%m/%d %H:%M").replace(
                tzinfo=timezone.utc).timestamp()
        # Amount does not enter the four-feature GNN. Avoid mixing currencies.
        yield (index, f"{row[1]}:{row[2]}", f"{row[3]}:{row[4]}", 0,
               time_cache[timestamp], int(row[label_at]))


def prepare(stream, output, scratch):
    with sqlite3.connect(scratch) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE settled (id INTEGER PRIMARY KEY, sender TEXT, recipient TEXT,
                amount_minor INTEGER, settled_at REAL, label INTEGER);
        """)
        db.executemany("INSERT INTO settled VALUES (?, ?, ?, ?, ?, ?)", transactions(stream))
        print("Transactions loaded; indexing history.", flush=True)
        db.executescript("""
            CREATE INDEX sender_history ON settled(sender, settled_at);
            CREATE INDEX recipient_history ON settled(recipient, settled_at);
            CREATE INDEX label_history ON settled(label, settled_at);
            CREATE INDEX chronology ON settled(settled_at);
        """)
        earliest, latest, count = db.execute(
            "SELECT min(settled_at), max(settled_at), count(*) FROM settled"
        ).fetchone()
        if not count or earliest == latest:
            raise ValueError("Expected transactions at multiple timestamps")
        cutoff = db.execute(
            "SELECT settled_at FROM settled ORDER BY settled_at LIMIT 1 OFFSET ?", (count * 4 // 5,)
        ).fetchone()[0]
        db.create_function("sample_order", 1, lambda i: (i * 2654435761) & 0xFFFFFFFF, deterministic=True)
        for name, operator, positives, negatives in (("train", "<", 1500, 6000), ("test", ">=", 400, 3200)):
            counts = {}
            with (output / f"{name}.jsonl").open("w") as destination:
                for label, limit in ((0, negatives), (1, positives)):
                    rows = db.execute(
                        f"SELECT * FROM settled WHERE label=? AND settled_at {operator} ? "
                        "ORDER BY sample_order(id) LIMIT ?", (label, cutoff, limit)
                    ).fetchall()
                    if not rows:
                        raise ValueError(f"{name} has no examples for label {label}")
                    counts[label] = len(rows)
                    for row in rows:
                        now = row["settled_at"]
                        history, _ = context(db, row["recipient"], now, before_only=True)
                        # IBM does not provide account ages. Use the mature-account default.
                        graph = analyze(history, row["sender"], row["recipient"], 365, now)
                        example = {"id": str(row["id"]), "label": label, "timestamp": now,
                                   "features": graph["features"], "edges": graph["edge_index"]}
                        destination.write(json.dumps(example, separators=(",", ":")) + "\n")
            print(f"{name}: {counts}", flush=True)
        return {"transactions": count, "train_test_cutoff_utc": datetime.fromtimestamp(
            cutoff, tz=timezone.utc).isoformat(), "sampling": "class-stratified within each time period"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--member", default="HI-Small_Trans.csv")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output) as scratch:
        db = Path(scratch) / "history.sqlite3"
        if args.archive.suffix.lower() == ".csv":
            with args.archive.open(encoding="utf-8-sig", newline="") as stream:
                report = prepare(stream, args.output, db)
        else:
            with ZipFile(args.archive) as archive:
                matches = [item for item in archive.namelist() if Path(item).name == args.member]
                if len(matches) != 1:
                    parser.error(f"Expected one {args.member}. Available files: {', '.join(archive.namelist())}")
                with archive.open(matches[0]) as raw:
                    with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                        report = prepare(stream, args.output, db)
    (args.output / "dataset.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
