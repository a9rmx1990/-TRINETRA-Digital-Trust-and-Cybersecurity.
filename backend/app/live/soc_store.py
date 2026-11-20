"""Transactional outbox and leased delivery of committed case events."""

import time
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS soc_jobs (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(payment_id),
    case_version INTEGER NOT NULL, trigger_kind TEXT NOT NULL,
    available_at DOUBLE PRECISION NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, error TEXT,
    published_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS soc_jobs_due ON soc_jobs(status, available_at);
CREATE INDEX IF NOT EXISTS soc_jobs_case ON soc_jobs(case_id);
CREATE TABLE IF NOT EXISTS soc_tool_audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES cases(payment_id),
    run_id TEXT NOT NULL, role TEXT NOT NULL, tool TEXT NOT NULL, arguments TEXT NOT NULL,
    outcome TEXT NOT NULL, result TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS soc_audit_case ON soc_tool_audit(case_id, seq);
"""
CASE_TRIGGERS = {
    "PAYMENT_EVALUATED", "ISSUE_CHALLENGE", "RELEASE", "CONFIRM_FREEZE",
    "CHALLENGE_VERIFIED", "SOC_WATCH_SIGNAL", "SOC_VERDICT_OVERRIDE",
}
MAX_ATTEMPTS = 4
LEASE_SECONDS = 90


def enqueue(db, job_id, case_id, kind, now):
    db.execute(
        "INSERT INTO soc_jobs(id,case_id,case_version,trigger_kind,available_at) "
        "SELECT ?,payment_id,version,?,? FROM cases WHERE payment_id=? "
        "ON CONFLICT(id) DO NOTHING", (job_id, kind, now, case_id),
    )


def retry_delay(attempts):
    return min(60, 2 ** attempts)


class SocJobs:
    def __init__(self, ledger):
        self.ledger = ledger

    def backfill(self):
        with self.ledger.tx(write=True) as db:
            db.execute("""
                INSERT INTO soc_jobs(id,case_id,case_version,trigger_kind,available_at)
                SELECT 'backfill:' || payment_id,payment_id,version,'BACKFILL',?
                FROM cases WHERE status='OPEN'
                AND NOT EXISTS (SELECT 1 FROM soc_jobs WHERE case_id=payment_id)
                ON CONFLICT(id) DO NOTHING
            """, (time.time(),))

    def claim(self, now, job_id=None):
        with self.ledger.tx(write=True) as db:
            db.execute("""
                UPDATE soc_jobs SET status='failed',lease=NULL,error='LeaseExpired'
                WHERE status='leased' AND available_at<=? AND attempts>=?
            """, (now, MAX_ATTEMPTS))
            query = """
                SELECT j.* FROM soc_jobs j JOIN cases c ON c.payment_id=j.case_id
                WHERE j.status IN ('pending','leased') AND j.available_at<=? AND j.attempts<?
            """
            args = (now, MAX_ATTEMPTS)
            if job_id is not None:
                query += " AND j.id=?"
                args += (job_id,)
            row = db.execute(query + " ORDER BY c.priority DESC,j.available_at,j.id LIMIT 1", args).fetchone()
            if row is None:
                return None
            lease = uuid4().hex
            db.execute("UPDATE soc_jobs SET status='leased',attempts=attempts+1,lease=?,available_at=? WHERE id=?",
                       (lease, now + LEASE_SECONDS, row["id"]))
            return dict(row) | {"lease": lease, "attempts": row["attempts"] + 1}

    @staticmethod
    def current(db, job):
        return db.execute(
            "SELECT 1 FROM soc_jobs WHERE id=? AND lease=? AND status='leased' AND available_at>?",
            (job["id"], job["lease"], time.time()),
        ).fetchone() is not None

    def complete(self, job, assessment=None):
        with self.ledger.tx(write=True) as db:
            if not self.current(db, job):
                return False
            case = db.execute("SELECT version FROM cases WHERE payment_id=?", (job["case_id"],)).fetchone()
            if assessment is not None and case["version"] == job["case_version"]:
                self.ledger.monitor.record_report(db, job["case_id"], assessment)
                self.ledger.record_triage(db, job["case_id"], assessment)
                if "verdict" in assessment:
                    self.ledger.actions.register(db, job, assessment["verdict"])
            db.execute("UPDATE soc_jobs SET status='done',lease=NULL,error=NULL WHERE id=?", (job["id"],))
            return True

    def fail(self, job, now, error):
        status = "failed" if job["attempts"] >= MAX_ATTEMPTS else "pending"
        with self.ledger.tx(write=True) as db:
            db.execute("""
                UPDATE soc_jobs SET status=?,available_at=?,lease=NULL,error=?
                WHERE id=? AND lease=? AND status='leased'
            """, (status, now + retry_delay(job["attempts"]), error, job["id"], job["lease"]))
