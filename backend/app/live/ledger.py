"""SQLite ledger and atomic local sandbox settlement."""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .database import Database
from .graph import analyze, context
from .models import models
from .soc_actions import Actions, SCHEMA as ACTION_SCHEMA
from .soc_monitor import Monitor, SCHEMA as MONITOR_SCHEMA
from .soc_store import CASE_TRIGGERS, SCHEMA as SOC_SCHEMA, SocJobs, enqueue
from .triage import prepare

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "sandbox.sqlite3"
POLICY = "sandbox-models-v3"
DEMO_ACCOUNT = "ACC-1001"
RECIPIENTS = {"ACC-2002": 365, "ACC-NEW-2003": 8, "MULE-NODE-1": 4}

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
    created DOUBLE PRECISION NOT NULL, UNIQUE(owner, request_key)
);
CREATE INDEX IF NOT EXISTS payments_created ON payments(created);
CREATE TABLE IF NOT EXISTS settled (
    id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
    amount_minor INTEGER NOT NULL, settled_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS settled_sender ON settled(sender, settled_at);
CREATE INDEX IF NOT EXISTS settled_recipient ON settled(recipient, settled_at);
CREATE TABLE IF NOT EXISTS cases (
    payment_id TEXT PRIMARY KEY REFERENCES payments(id),
    priority DOUBLE PRECISION NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS case_triage (
    payment_id TEXT PRIMARY KEY REFERENCES cases(payment_id),
    assessment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT NOT NULL,
    kind TEXT NOT NULL, actor TEXT NOT NULL, time DOUBLE PRECISION NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_payment_kind ON events(payment_id, kind);
CREATE TABLE IF NOT EXISTS restrictions (account TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS challenges (
    payment_id TEXT PRIMARY KEY REFERENCES payments(id),
    proof_hash TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL, attempts INTEGER NOT NULL
);
"""


class Ledger:
    def __init__(self, path, *, database_url=None):
        self.database = Database(path, database_url, SCHEMA + SOC_SCHEMA + ACTION_SCHEMA + MONITOR_SCHEMA)
        self.jobs = SocJobs(self)
        self.actions = Actions(self)
        self.monitor = Monitor(self)

    def tx(self, write=False):
        return self.database.tx(write=write)

    def payment(self, db, pid, owner=None):
        row = db.execute("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()
        if not row or (owner is not None and row["owner"] != owner):
            raise HTTPException(404, "Payment unavailable")
        return row

    @staticmethod
    def result(row):
        return json.loads(row["payload"]) | {"payment_id": row["id"], "state": row["state"]}

    def get(self, pid, owner):
        with self.tx() as db:
            return self.result(self.payment(db, pid, owner))

    @staticmethod
    def blocked(db, recipient):
        return bool(db.execute("SELECT 1 FROM restrictions WHERE account IN (?, ?)",
                               (DEMO_ACCOUNT, recipient)).fetchone())

    def event(self, db, pid, kind, actor, detail):
        now = time.time()
        row = db.execute("INSERT INTO events(payment_id,kind,actor,time,detail) VALUES (?,?,?,?,?) RETURNING seq",
                         (pid, kind, actor, now, json.dumps(detail))).fetchone()
        analyst_effect = kind == "SOC_ACTION" and actor == "sandbox-analyst" and detail["outcome"] == "applied"
        if kind in CASE_TRIGGERS or analyst_effect:
            enqueue(db, f"event:{row['seq']}", pid, kind, now)

    def settle(self, db, pid, payload, allowed_state):
        if db.execute("SELECT 1 FROM soc_holds WHERE case_id=? AND expires_at>?", (pid, time.time())).fetchone():
            raise HTTPException(409, "Temporary SOC hold prevents settlement")
        if self.blocked(db, payload["recipient"]):
            raise HTTPException(409, "An account restriction prevents settlement")
        if allowed_state in {"HELD", "STEP_UP_REQUIRED"} and payload["policy_version"] not in {POLICY, "sandbox-models-v2"}:
            now = time.time()
            recipient = payload["recipient"]
            rows, _ = context(db, recipient, now)
            latest = analyze(rows, DEMO_ACCOUNT, recipient, RECIPIENTS[recipient], now)
            if latest["score"] >= 85 and (allowed_state == "STEP_UP_REQUIRED" or
                                          latest["score"] > payload["evidence"]["graph"]["score"]):
                raise HTTPException(409, "Current graph risk requires a new review")
        changed = db.execute("UPDATE payments SET state='SETTLED' WHERE id=? AND state=?",
                             (pid, allowed_state))
        if changed.rowcount != 1:
            raise HTTPException(409, "Payment state changed")
        db.execute("INSERT INTO settled VALUES (?, ?, ?, ?, ?)",
                   (pid, DEMO_ACCOUNT, payload["recipient"], payload["amount_minor"], time.time()))

    def seed(self, db, now):
        for hop in range(1, 6):
            db.execute("INSERT INTO settled VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE "
                       "SET sender=excluded.sender,recipient=excluded.recipient,amount_minor=excluded.amount_minor,"
                       "settled_at=excluded.settled_at",
                       (f"fixture:mule:{hop}", f"MULE-NODE-{hop}", f"MULE-NODE-{hop+1}",
                        500_000 - hop * 1000, now - 100 + hop * 3))

    @staticmethod
    def fingerprint(rows):
        return {(row["id"], row["settled_at"]) for row in rows}

    def score_recipient(self, recipient):
        if recipient not in RECIPIENTS or not models.configured("graph"):
            return {"status": "missing"}, None
        now = time.time()
        with self.tx() as db:
            rows, _ = context(db, recipient, now)
        snapshot = analyze(rows, DEMO_ACCOUNT, recipient, RECIPIENTS[recipient], now)
        return models.graph_score(snapshot["features"], snapshot["edge_index"]), self.fingerprint(rows)

    def submit(self, owner, key, request, evidence, narrative_signal, scenario=None, graph_result=None):
        request_hash = hashlib.sha256(json.dumps([request, scenario], sort_keys=True).encode()).hexdigest()
        recipient = request["recipient"]
        if recipient not in RECIPIENTS:
            raise HTTPException(422, "Select a sandbox recipient")

        def replay(db):
            prior = db.execute("SELECT * FROM payments WHERE owner=? AND request_key=?", (owner, key)).fetchone()
            if not prior:
                return None
            if prior["request_hash"] != request_hash:
                raise HTTPException(409, "Request key already belongs to another payment")
            return self.result(prior)

        gnn, scored_rows = graph_result or ({"status": "missing"}, None)

        with self.tx(write=True) as db:
            if result := replay(db):
                return result
            now = time.time()
            if scenario == "mule":
                self.seed(db, now)
            rows, truncated = context(db, recipient, now)
            if scored_rows is not None and scored_rows != self.fingerprint(rows):
                gnn = {"status": "stale", "version": gnn.get("version")}
            graph = analyze(rows, DEMO_ACCOUNT, recipient, RECIPIENTS[recipient], now)
            graph["truncated"] |= truncated
            del graph["features"], graph["edge_index"]
            payload = decide(request, evidence, narrative_signal, graph, gnn,
                             self.blocked(db, recipient), fixture=scenario is not None)
            pid = uuid4().hex
            state = {"ALLOW": "AUTHORIZED", "STEP_UP": "STEP_UP_REQUIRED", "HOLD": "HELD", "BLOCK": "BLOCKED"}[payload["decision"]]
            db.execute("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (pid, owner, key, request_hash, state, json.dumps(payload), now))
            if state == "AUTHORIZED":
                self.settle(db, pid, payload, state)
            else:
                db.execute("INSERT INTO cases VALUES (?, ?, 'OPEN', 1)",
                           (pid, payload["risk_score"] / 100 * request["amount_minor"]))
                db.execute("INSERT INTO case_triage VALUES (?, ?)", (pid, json.dumps(prepare(payload))))
            self.event(db, pid, "PAYMENT_EVALUATED", owner, {"decision": payload["decision"]})
            return self.result(self.payment(db, pid))

    @staticmethod
    def changes(db, after):
        rows = db.execute("SELECT seq, payment_id FROM events WHERE seq>? ORDER BY seq LIMIT 250",
                          (after,)).fetchall()
        return {"cursor": rows[-1]["seq"] if rows else after,
                "updated_ids": list(dict.fromkeys(row["payment_id"] for row in rows))}

    def updates(self, after):
        with self.tx() as db:
            return self.changes(db, after)

    def cases(self, after, include_closed=False):
        with self.tx() as db:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT payments.*, cases.priority, cases.status, cases.version FROM cases "
                "JOIN payments ON payment_id=id WHERE status='OPEN' OR ? "
                "ORDER BY (status='OPEN') DESC, (priority + MAX(0, ? - created) / 60.0) DESC LIMIT 50",
                (include_closed, time.time())).fetchall()
            recent = db.execute(
                "SELECT payments.*, cases.payment_id IS NOT NULL AS has_case FROM payments "
                "LEFT JOIN cases ON payments.id=cases.payment_id ORDER BY created DESC, id DESC LIMIT 12"
            ).fetchall()
            return self.changes(db, after) | {
                "cases": [self.case_brief(row) for row in rows],
                "recent": [payment_brief(self.result(row)) | {"has_case": bool(row["has_case"])}
                           for row in recent],
                "overview": self.overview(db),
            }

    def case_brief(self, row):
        payload = self.result(row)
        return payment_brief(payload) | {"risk_score": payload["risk_score"], "priority": row["priority"],
                                         "case_status": row["status"], "version": row["version"]}

    def overview(self, db):
        days = 7
        start = (int(time.time()) // 86400 - days + 1) * 86400
        totals = db.execute("""
            SELECT count(*) AS payments, count(DISTINCT payments.owner) AS sessions,
                   count(cases.payment_id) AS flagged,
                   count(CASE WHEN cases.status='OPEN' THEN 1 END) AS open,
                   count(CASE WHEN json_extract(assessment, '$.investigated_at') IS NOT NULL THEN 1 END) AS investigated,
                   count(CASE WHEN json_extract(assessment, '$.provider_status')='complete' THEN 1 END) AS ai_assessed
              FROM payments LEFT JOIN cases ON payments.id=cases.payment_id
              LEFT JOIN case_triage ON payments.id=case_triage.payment_id
             WHERE payments.created>=?
        """, (start,)).fetchone()
        daily = db.execute("""
            SELECT CAST(FLOOR(payments.created / 86400) AS BIGINT) * 86400 AS day,
                   count(*) AS payments, count(cases.payment_id) AS flagged
              FROM payments LEFT JOIN cases ON payments.id=cases.payment_id
             WHERE created>=? GROUP BY day
        """, (start,)).fetchall()
        by_day = {row["day"]: dict(row) for row in daily}
        return dict(totals) | {
            "daily": [by_day.get(day, {"day": day, "payments": 0, "flagged": 0})
                      for day in range(start, start + days * 86400, 86400)]
        }

    def investigation_history(self, pid):
        with self.tx() as db:
            db.execute("BEGIN")
            current = self.payment(db, pid)
            recipient = self.result(current)["recipient"]
            args = (current["owner"], recipient, current["created"] - 30 * 86400, current["created"])
            linked = """
                WITH history AS (
                    SELECT payments.id, payments.created, payments.state, cases.status,
                           owner=? AS same_session, json_extract(payload, '$.recipient')=? AS same_recipient
                      FROM payments LEFT JOIN cases ON payments.id=cases.payment_id
                     WHERE payments.created>=? AND payments.created<?
                )
            """
            counts = db.execute(linked + """
                SELECT count(CASE WHEN same_session THEN 1 END) AS session_payments,
                       count(CASE WHEN same_session AND status IS NOT NULL THEN 1 END) AS session_flagged,
                       count(CASE WHEN same_recipient THEN 1 END) AS recipient_payments,
                       count(CASE WHEN same_recipient AND status IS NOT NULL THEN 1 END) AS recipient_flagged,
                       count(CASE WHEN same_recipient AND NOT same_session AND status IS NOT NULL
                                  THEN 1 END) AS other_session_recipient_flagged
                  FROM history
            """, args).fetchone()
            cases = db.execute(linked + """
                SELECT id AS payment_id, created, state, same_session, same_recipient
                  FROM history WHERE status IS NOT NULL AND (same_session OR same_recipient)
                 ORDER BY created DESC, id LIMIT 5
            """, args).fetchall()
            related = [dict(row) | {"same_session": int(row["same_session"]),
                                    "same_recipient": int(row["same_recipient"])} for row in cases]
            return dict(counts) | {"lookback_days": 30, "related_cases": related}

    def save_triage(self, pid, assessment, expected_version):
        with self.tx(write=True) as db:
            row = db.execute("SELECT version FROM cases WHERE payment_id=?", (pid,)).fetchone()
            if not row or row["version"] != expected_version:
                raise HTTPException(409, "Refresh the case before saving the assessment")
            self.monitor.record_report(db, pid, assessment)
            self.record_triage(db, pid, assessment)

    def record_triage(self, db, pid, assessment):
        db.execute("INSERT INTO case_triage VALUES (?, ?) ON CONFLICT(payment_id) "
                   "DO UPDATE SET assessment=excluded.assessment", (pid, json.dumps(assessment)))
        self.event(db, pid, "SOC_INVESTIGATION_COMPLETED", "soc-assistant",
                   {"source": assessment["source"], "provider_status": assessment["provider_status"]})

    def case(self, pid):
        with self.tx() as db:
            db.execute("BEGIN")
            row = self.payment(db, pid)
            case = db.execute("SELECT * FROM cases WHERE payment_id=?", (pid,)).fetchone()
            if not case:
                raise HTTPException(404, "Case unavailable")
            events = db.execute("SELECT seq,kind,actor,time,detail FROM events WHERE payment_id=? "
                                "ORDER BY seq DESC LIMIT 200", (pid,)).fetchall()
            payload = self.result(row)
            saved = db.execute("SELECT assessment FROM case_triage WHERE payment_id=?", (pid,)).fetchone()
            return payload | {"version": case["version"], "case_status": case["status"],
                              "triage": json.loads(saved["assessment"]) if saved else prepare(payload),
                                       "agent": self.actions.details(db, pid),
                                       "events": [dict(event) | {"detail": json.loads(event["detail"])}
                                                  for event in reversed(events)]}

    @staticmethod
    def put_challenge(db, pid, code, now):
        db.execute("INSERT INTO challenges VALUES (?,?,?,0) ON CONFLICT(payment_id) DO UPDATE SET "
                   "proof_hash=excluded.proof_hash,expires=excluded.expires,attempts=0",
                   (pid, hashlib.sha256(code.encode()).hexdigest(), now + 180))

    def action(self, pid, action, version, note):
        with self.tx(write=True) as db:
            row = self.payment(db, pid)
            case = db.execute("SELECT * FROM cases WHERE payment_id=?", (pid,)).fetchone()
            if not case or case["version"] != version or case["status"] != "OPEN":
                raise HTTPException(409, "Refresh the case before acting")
            payload = self.result(row)
            if action == "ISSUE_CHALLENGE":
                if row["state"] != "STEP_UP_REQUIRED":
                    raise HTTPException(409, "This payment does not require step-up")
                code = secrets.token_urlsafe(18)
                self.put_challenge(db, pid, code, time.time())
                response = {"challenge_code": code}
            elif action == "RELEASE":
                if row["state"] != "HELD":
                    raise HTTPException(409, "Only held payments can be released")
                self.settle(db, pid, payload, "HELD")
                response = {}
            else:
                if row["state"] != "HELD":
                    raise HTTPException(409, "Only held payments can confirm a freeze")
                db.execute("INSERT INTO restrictions VALUES (?) ON CONFLICT(account) DO NOTHING", (payload["recipient"],))
                response = {}
            db.execute("UPDATE cases SET version=version+1, status=? WHERE payment_id=?",
                       ("OPEN" if action == "ISSUE_CHALLENGE" else action, pid))
            self.event(db, pid, action, "sandbox-analyst", {"note": note})
            return self.result(self.payment(db, pid)) | response

    def verify(self, pid, owner, proof):
        with self.tx(write=True) as db:
            row = self.payment(db, pid, owner)
            challenge = db.execute("SELECT * FROM challenges WHERE payment_id=?", (pid,)).fetchone()
            if row["state"] != "STEP_UP_REQUIRED" or not challenge or challenge["attempts"] >= 5 or challenge["expires"] < time.time():
                raise HTTPException(409, "Request a current challenge from the sandbox analyst")
            digest = hashlib.sha256(proof.encode()).hexdigest()
            if secrets.compare_digest(challenge["proof_hash"], digest):
                self.settle(db, pid, self.result(row), "STEP_UP_REQUIRED")
                db.execute("DELETE FROM challenges WHERE payment_id=?", (pid,))
                db.execute("UPDATE cases SET status='VERIFIED', version=version+1 WHERE payment_id=?", (pid,))
                self.event(db, pid, "CHALLENGE_VERIFIED", owner, {})
                return self.result(self.payment(db, pid))
            db.execute("UPDATE challenges SET attempts=attempts+1 WHERE payment_id=?", (pid,))
        raise HTTPException(422, "Incorrect verification code")


def voice_verdict(signal, voiced_fraction):
    if signal.get("status") != "ready" or voiced_fraction < 0.35:
        return "inconclusive"
    settings = models.manifest.get("spoof", {})
    low, high = settings.get("reviewed_genuine_threshold"), settings.get("reviewed_hold_threshold")
    if not (isinstance(low, (int, float)) and isinstance(high, (int, float)) and 0 <= low < high <= 100):
        return "inconclusive"
    if signal["score"] >= high:
        return "suspected_synthetic"
    if signal["score"] <= low:
        return "likely_genuine"
    return "inconclusive"


def model_score(signal):
    return signal.get("score") if signal.get("status") == "ready" else None


def decide(request, evidence, narrative_signal, graph, gnn, restricted, *, fixture=False):
    acoustic = evidence["acoustic"] if evidence else {}
    spoken = evidence["coercion"] if evidence else {}
    spoof = acoustic.get("spoof", {})
    voiced = acoustic.get("voiced_fraction", 0)
    verdict = voice_verdict(spoof, voiced)
    voice = model_score(spoof) if verdict != "inconclusive" else None
    speech = model_score(spoken.get("coercion", {}))
    remark = model_score(narrative_signal)
    text = max((value for value in (speech, remark) if value is not None), default=None)
    graph_score = None if gnn.get("review_only") else model_score(gnn)
    try:
        fusion = models.fusion(voice, text, graph_score) if not fixture else {"status": "fixture"}
    except (ValueError, OSError, KeyError, TypeError):
        fusion = {"status": "unavailable"}

    reasons = []
    if fixture:
        rule_text, text_reasons, _ = models.nlp.analyze(request.get("narrative"))
        rule_voice = acoustic.get("baseline", {}).get("score", 0)
        rule_graph = graph["score"]
        risk = (0.4 * rule_graph + 0.15 * rule_text) / 0.55
        if acoustic:
            risk = 0.4 * rule_graph + 0.15 * rule_text + 0.45 * rule_voice
        if rule_voice >= 85 or rule_graph >= 85 or (rule_text >= 80 and rule_graph >= 20):
            risk = max(78, risk)
        elif rule_voice >= 50 or rule_text >= 80 or request.get("session_id"):
            risk = max(45, risk)
        reasons = graph["reasons"] + (text_reasons if rule_text else [])
    else:
        # Combine calibrated scores when the version-matched stacker is available.
        # The uncalibrated default uses the strongest learned signal only.
        risk = model_score(fusion)
        if risk is None:
            risk = max((score for score in (voice, text, graph_score) if score is not None), default=0)
        for label, score in (("Voice spoof model", voice), ("XLM-R transcript", speech),
                             ("XLM-R remark", remark), ("Recipient graph model", graph_score)):
            if score is not None:
                reasons.append(f"{label} risk score: {score:.1f}.")
        if gnn.get("review_only") and model_score(gnn) is not None:
            reasons.append(f"Recipient graph model score (review only): {gnn['score']:.1f}.")
        missing = []
        if verdict == "inconclusive":
            missing.append("voice screening")
        if speech is None:
            missing.append("transcript screening")
        if request.get("narrative", "").strip() and remark is None:
            missing.append("payment remark screening")
        if graph_score is None:
            missing.append("recipient graph scoring")
        if missing:
            risk = max(45, risk)
            reasons.append("Additional verification is required because evidence is missing or inconclusive: "
                           + ", ".join(missing) + ".")
        if verdict == "suspected_synthetic":
            risk = max(78, risk)
            reasons.insert(0, "Voice score crossed the reviewed synthetic speech threshold.")
        for name, score in (("coercion", text), ("graph", graph_score)):
            threshold = models.manifest.get(name, {}).get("reviewed_hold_threshold")
            if score is not None and isinstance(threshold, (float, int)) and 0 < threshold <= score:
                risk = max(78, risk)
                reasons.insert(0, f"The {name} model crossed its reviewed hold threshold.")

    if restricted:
        risk = 100
        reasons.insert(0, "Account restriction is active.")
    if not reasons:
        reasons = ["No scoring signal crossed the review threshold."]
    if restricted:
        decision = "BLOCK"
    else:
        decision = "HOLD" if risk >= 70 else "STEP_UP" if risk >= 35 else "ALLOW"
    return {"sender": DEMO_ACCOUNT, "recipient": request["recipient"], "channel": request["channel"],
            "amount_minor": request["amount_minor"], "currency": "INR", "decision": decision,
            "risk_score": round(risk, 2), "policy_version": "sandbox-fixtures-v1" if fixture else POLICY,
            "reasons": reasons, "voice_verdict": verdict, "evidence_id": evidence["latest"]["evidence_id"] if evidence else None,
            "evidence": {"call": evidence, "graph": graph, "gnn": gnn, "fusion": fusion,
                         "narrative_model": narrative_signal}}

def payment_brief(payment):
    return {key: payment[key] for key in (
        "payment_id", "recipient", "amount_minor", "currency", "state", "decision")}


def open_ledger():
    return Ledger(os.getenv("TRINETRA_DB", str(DEFAULT_PATH)), database_url=os.getenv("TRINETRA_DATABASE_URL"))
