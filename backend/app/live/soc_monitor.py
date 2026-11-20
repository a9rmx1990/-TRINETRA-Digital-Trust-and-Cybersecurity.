"""Durable watch scheduling, SOC reports and adjudicated feedback."""

import json
import math
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS soc_watches (
    case_id TEXT PRIMARY KEY REFERENCES cases(payment_id),
    through_at DOUBLE PRECISION NOT NULL, next_at DOUBLE PRECISION NOT NULL,
    cursor_seq BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS soc_watches_due ON soc_watches(status, next_at);
CREATE TABLE IF NOT EXISTS soc_reports (
    run_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(payment_id),
    verdict TEXT NOT NULL, report TEXT NOT NULL, features TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS soc_reports_case ON soc_reports(case_id, created_at);
"""
DAY = 86_400
WATCH_DAYS = 30


def next_watch(now, through):
    return min(now + DAY, through)


def similarity(first, second):
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if not first_norm or not second_norm:
        return 0.0
    return sum(a * b for a, b in zip(first, second, strict=True)) / (first_norm * second_norm)


class Monitor:
    def __init__(self, ledger):
        self.ledger = ledger

    def schedule(self, db, case_id, now, *, expedited=False):
        initial_event = db.execute("SELECT COALESCE(MIN(seq),0) AS first FROM events WHERE payment_id=?",
                                   (case_id,)).fetchone()["first"]
        through = now + WATCH_DAYS * DAY
        db.execute("INSERT INTO soc_watches(case_id,through_at,next_at,cursor_seq) VALUES (?,?,?,?) "
                   "ON CONFLICT(case_id) DO NOTHING",
                   (case_id, through, now if expedited else next_watch(now, through), initial_event))
        if expedited:
            db.execute("UPDATE soc_watches SET next_at=? WHERE case_id=? AND status='active' AND next_at>?",
                       (now, case_id, now))
        return self.details(db, case_id)

    @staticmethod
    def details(db, case_id):
        row = db.execute("SELECT through_at,next_at,status FROM soc_watches WHERE case_id=?",
                         (case_id,)).fetchone()
        return dict(row) if row else None

    def tick(self, now):
        with self.ledger.tx(write=True) as db:
            watch = db.execute("SELECT * FROM soc_watches WHERE status='active' AND next_at<=? "
                               "ORDER BY next_at,case_id LIMIT 1", (now,)).fetchone()
            if not watch:
                return False
            case_id = watch["case_id"]
            cutoff = min(now, watch["through_at"])
            recipient = self.ledger.result(self.ledger.payment(db, case_id))["recipient"]
            rows = db.execute("""
                SELECT e.seq,e.payment_id FROM events e JOIN payments p ON p.id=e.payment_id
                WHERE e.seq>? AND e.time<=? AND e.payment_id<>? AND e.kind='PAYMENT_EVALUATED'
                AND json_extract(p.payload, '$.recipient')=? AND json_extract(p.payload, '$.decision') IN ('HOLD','BLOCK')
                ORDER BY e.seq LIMIT 5
            """, (watch["cursor_seq"], cutoff, case_id, recipient)).fetchall()
            cursor = db.execute("SELECT COALESCE(MAX(seq),0) AS seq FROM events WHERE time<=?",
                                (cutoff,)).fetchone()["seq"]
            db.execute("UPDATE soc_watches SET status=?,next_at=?,cursor_seq=? WHERE case_id=?",
                       ("expired" if now >= watch["through_at"] else "active",
                        next_watch(now, watch["through_at"]), max(cursor, watch["cursor_seq"]), case_id))
            if rows:
                db.execute("UPDATE cases SET status='OPEN',version=version+1 WHERE payment_id=?", (case_id,))
                self.ledger.event(db, case_id, "SOC_WATCH_SIGNAL", "soc-monitor",
                                  {"related": [{"case_id": row["payment_id"], "event_id": f"event:{row['seq']}"}
                                               for row in rows]})
            else:
                self.ledger.event(db, case_id, "SOC_WATCH_CHECKED", "soc-monitor", {"through": cutoff})
            return True

    def record_report(self, db, case_id, assessment):
        report = assessment.get("report")
        if report is None:
            return
        db.execute("INSERT INTO soc_reports VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING",
                   (assessment["run_id"], case_id, json.dumps(assessment["verdict"]), json.dumps(report),
                    json.dumps(assessment.get("features", [])), time.time()))

    def similar(self, case_id, features):
        with self.ledger.tx() as db:
            rows = db.execute("""
                SELECT r.case_id,r.features FROM soc_reports r JOIN cases c ON c.payment_id=r.case_id
                WHERE c.status<>'OPEN' AND r.case_id<>? ORDER BY r.created_at DESC LIMIT 100
            """, (case_id,)).fetchall()
        scored = {}
        for row in rows:
            vector = json.loads(row["features"])
            if len(vector) == len(features):
                scored.setdefault(row["case_id"], similarity(features, vector))
        return [{"case_id": key, "similarity": round(score, 3)}
                for key, score in sorted(scored.items(), key=lambda row: (-row[1], row[0]))[:5] if score > 0]

    def analytics(self):
        with self.ledger.tx() as db:
            grouped = {
                "jobs": ("soc_jobs", "status"),
                "watches": ("soc_watches", "status"),
                "actions": ("soc_proposals", "status"),
                "analyst_labels": ("soc_feedback", "verdict"),
            }
            return {
                "schema_version": 1,
                "activity": self.ledger.overview(db),
                "reports": db.execute("SELECT count(*) AS total FROM soc_reports").fetchone()["total"],
                **{key: {row[field]: row["total"] for row in db.execute(
                    f"SELECT {field},count(*) AS total FROM {table} GROUP BY {field}"
                ).fetchall()} for key, (table, field) in grouped.items()},
            }

    def evaluation(self):
        with self.ledger.tx() as db:
            rows = db.execute("""
                SELECT f.case_id,f.verdict,f.created_at,p.state,
                       (SELECT r.verdict FROM soc_reports r WHERE r.case_id=f.case_id
                        AND r.created_at<=f.created_at ORDER BY r.created_at DESC,r.run_id LIMIT 1) AS prediction
                FROM soc_feedback f JOIN payments p ON p.id=f.case_id
                WHERE NOT EXISTS (SELECT 1 FROM soc_feedback newer WHERE newer.case_id=f.case_id AND newer.seq>f.seq)
                ORDER BY f.seq DESC LIMIT 500
            """).fetchall()
        return [{"case_id": row["case_id"], "label": row["verdict"], "payment_state": row["state"],
                 "prediction": json.loads(row["prediction"])["verdict"] if row["prediction"] else None}
                for row in rows]
