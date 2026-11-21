"""SOC worker: claims committed outbox jobs under a lease and runs the five stages.

Triage -> Investigator -> Decision -> Monitor -> Reporter. Reads go through
case-scoped MCP tools; writes (proposal, watch, report) are applied in one fenced
transaction that requires the lease token and the case version observed at the start.
A stale worker cannot overwrite newer state.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from functools import lru_cache
from typing import Any

from .. import clock
from ..config import settings
from ..db import Database, Tx, dumps, get_db, loads
from ..events import append_event, enqueue
from ..util import new_id
from . import actions
from .mcp import ToolError, call_tool, call_tool_in_tx

log = logging.getLogger("trinetra.worker")

AGENT = "soc-agent"


def _tracing_enabled() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY") and os.getenv("LANGSMITH_TRACING", "").lower() == "true")


@lru_cache(maxsize=1)
def _trace_client():
    from langsmith import Client
    return Client(api_key=os.environ["LANGSMITH_API_KEY"], hide_inputs=True, hide_outputs=True, hide_metadata=True)


def _agent_span(name: str, fn):
    """Optional LangSmith span with deliberately content-free input and output."""
    if not _tracing_enabled():
        return fn()
    try:
        from langsmith import traceable, tracing_context
    except ImportError:
        log.warning("LangSmith is enabled but the package is unavailable; running %s without tracing", name)
        return fn()
    completed = False
    result = None
    failure: BaseException | None = None

    def invoke():
        nonlocal completed, result, failure
        try:
            result = fn()
            completed = True
            return result
        except BaseException as exc:
            failure = exc
            raise

    try:
        traced = traceable(
            invoke, name=name, run_type="chain", client=_trace_client(),
            project_name=os.getenv("LANGSMITH_PROJECT") or "trinetra-soc",
            process_inputs=lambda _: {"stage": name},
            process_outputs=lambda _: {"completed": True},
        )
        with tracing_context(enabled=True, client=_trace_client(),
                             project_name=os.getenv("LANGSMITH_PROJECT") or "trinetra-soc"):
            return traced()
    except Exception as exc:
        if completed:
            return result
        if failure is not None:
            raise failure
        log.warning("LangSmith span %s failed before execution: %s", name, type(exc).__name__)
        return fn()


def _measured_stage(metrics: dict, name: str, fn):
    started = time.monotonic()
    try:
        return _agent_span(name, fn)
    finally:
        metrics[name] = {"duration_ms": int((time.monotonic() - started) * 1000)}


class FenceLost(Exception):
    pass


def claim(db: Database, worker_id: str) -> dict | None:
    now = clock.now_ms()
    token = new_id("lease")

    def _go(t: Tx):
        sql = ("SELECT * FROM outbox WHERE ((status = 'pending' AND next_due_ms <= ?) OR"
               " (status = 'leased' AND lease_until_ms < ?)) ORDER BY next_due_ms, created_ms LIMIT 1")
        if db.dialect == "postgres":
            sql += " FOR UPDATE SKIP LOCKED"
        job = t.one(sql, (now, now))
        if not job:
            return None
        if job["attempts"] >= job["max_attempts"]:
            t.execute("UPDATE outbox SET status = 'failed', completed_ms = ?, lease_token = NULL WHERE id = ?",
                      (now, job["id"]))
            return None
        n = t.rowcount("UPDATE outbox SET status = 'leased', lease_token = ?, lease_until_ms = ?, attempts = attempts + 1"
                       " WHERE id = ? AND (lease_token IS NULL OR lease_token = ?)",
                       (token, now + settings.lease_ms, job["id"], job["lease_token"]))
        if n != 1:
            return None
        return {**job, "lease_token": token, "attempts": job["attempts"] + 1}
    return db.write(_go)


def _check_fence(t: Tx, job: dict, case_version: int | None) -> dict:
    j = t.one("SELECT lease_token, status FROM outbox WHERE id = ?", (job["id"],))
    if not j or j["lease_token"] != job["lease_token"] or j["status"] != "leased":
        raise FenceLost("lease lost")
    t.lock_rows("cases", [job["case_id"]])
    c = t.one("SELECT * FROM cases WHERE id = ?", (job["case_id"],))
    if case_version is not None and c["version"] != case_version:
        raise FenceLost("case version changed")
    return c


def complete(t: Tx, job: dict) -> None:
    t.execute("UPDATE outbox SET status = 'done', completed_ms = ?, lease_token = NULL WHERE id = ? AND lease_token = ?",
              (clock.now_ms(), job["id"], job["lease_token"]))


def _retry(db: Database, job: dict, err: str, count_attempt: bool = True) -> None:
    backoff = min(60_000, 500 * (2 ** max(0, job["attempts"] - 1)))
    def _go(t: Tx):
        adj = "" if count_attempt else ", attempts = attempts - 1"
        t.execute(f"UPDATE outbox SET status = 'pending', lease_token = NULL, next_due_ms = ?, last_error = ?{adj}"
                  " WHERE id = ? AND lease_token = ?", (clock.now_ms() + backoff, err[:300], job["id"], job["lease_token"]))
    db.write(_go)


# ------------------------------------------------------------------ pipeline
def _evidence_ids(ev: list[dict], *kinds: str) -> list[str]:
    return [e["id"] for e in ev if e["kind"] in kinds]


def investigate(job: dict) -> dict:
    cid = job["case_id"]
    started = time.monotonic()
    stage_metrics: dict[str, dict] = {}
    # Triage
    snap, history = _measured_stage(stage_metrics, "Triage", lambda: (
        call_tool("triage", "case.get", {"case_id": cid}, actor=AGENT),
        call_tool("triage", "case.history", {"case_id": cid}, actor=AGENT),
    ))
    stage_metrics["Triage"]["tool_calls"] = 2
    version = snap["case"]["version"]
    # Investigator
    call_ev, graph, model_ev, similar = _measured_stage(stage_metrics, "Investigator", lambda: (
        call_tool("investigator", "call.evidence", {"case_id": cid}, actor=AGENT),
        call_tool("investigator", "graph.get", {"case_id": cid}, actor=AGENT),
        call_tool("investigator", "model.evidence", {"case_id": cid}, actor=AGENT),
        call_tool("investigator", "cases.similar_closed", {"case_id": cid}, actor=AGENT),
    ))
    stage_metrics["Investigator"]["tool_calls"] = 4

    pay = snap["payment"]
    reasons = pay["reasons"]
    codes = {r["code"] for r in reasons}
    holdish = any(r["effect"] == "HOLD" for r in reasons)
    prior_fraud = [s for s in similar if s.get("verdict") == "fraud"]

    # Decision (deterministic local evidence report; an optional loopback model could replace this step)
    signal_ids = _evidence_ids(model_ev, "voice_authenticity", "speech_content", "typed_remark", "recipient_graph")
    graph_ids = _evidence_ids(model_ev, "recipient_graph_snapshot", "recipient_graph")
    speech_ids = _evidence_ids(model_ev, "speech_content", "typed_remark", "transcript")
    proposals: list[dict] = []
    def decide():
        if pay["decision"] == "BLOCK":
            verdict, confidence = "blocked_by_restriction", "high"
            rationale = "Gateway blocked the transfer because an active restriction applies."
            cited = signal_ids
        elif holdish or prior_fraud:
            verdict, confidence = "likely_fraud", "medium" if holdish else "low"
            bits = [r["text"] for r in reasons if r["effect"] in ("HOLD", "STEP_UP")]
            if prior_fraud:
                bits.append(f"{len(prior_fraud)} closed case(s) involving this contact were adjudicated fraud")
            rationale = "; ".join(bits)
            cited = graph_ids + speech_ids
            if pay["state"] == "VERIFICATION_REQUIRED":
                proposals.append({"action": "place_hold", "rationale": "Hold verification until an analyst reviews the fraud indicators."})
            proposals.append({"action": "restrict_counterparty",
                              "rationale": "Restrict the contact to stop further transfers while the case is reviewed."})
        elif pay["state"] == "VERIFICATION_REQUIRED":
            verdict, confidence = "needs_customer_verification", "medium"
            rationale = "; ".join(r["text"] for r in reasons if r["effect"] == "STEP_UP") or "Additional verification required."
            cited = signal_ids
            if pay["direction"] == "outgoing":
                proposals.append({"action": "issue_challenge",
                                  "rationale": "Issue a sandbox verification code to the customer after confirming identity out of band."})
        elif pay["state"] == "HELD":
            verdict, confidence = "insufficient_evidence", "low"
            rationale = "Hold present without corroborating evidence."
            cited = signal_ids
            proposals.append({"action": "release", "rationale": "Release if the analyst confirms the hold evidence is weak."})
        else:
            verdict, confidence = "no_action", "medium"
            rationale = "Payment already terminal."
            cited = signal_ids
        return verdict, confidence, rationale, list(dict.fromkeys(cited)) or signal_ids

    verdict, confidence, rationale, cited = _measured_stage(stage_metrics, "Decision", decide)
    stage_metrics["Decision"]["tool_calls"] = len(proposals)
    cited = list(dict.fromkeys(cited)) or signal_ids

    unavailable = [k for k, v in (pay["signals"] or {}).items() if v.get("status") in ("unavailable", "inconclusive", "unsupported_language")]
    relation = "from" if pay["direction"] == "incoming" else "to"
    alert = (f"{verdict.replace('_', ' ').capitalize()} · {pay['amount_display']} via {pay['channel']} {relation} "
             f"{pay['beneficiary']['name']} ({pay['beneficiary']['masked']}). {rationale}")
    report = {
        "verdict": verdict, "confidence": confidence, "confidence_basis": "rule-based evidence report, not a model probability",
        "rationale": rationale, "evidence_ids": cited, "alert": alert,
        "signals_unavailable": unavailable,
        "graph": {"truncated": graph.get("truncated"), "features": graph.get("features")},
        "capture": (call_ev.get("capture_quality") or {}).get("payload", {}).get("voiced_ms"),
        "history_count": len(history), "similar_closed": [s["id"] for s in similar],
        "metrics": {"tool_calls": 8 + len(proposals), "evidence_items": len(model_ev),
                    "duration_ms": 0, "stages": stage_metrics, "started_monotonic": started},
        "generated_by": AGENT, "case_version_read": version,
    }
    return {"version": version, "report": report, "proposals": proposals, "cited": cited}


def commit_investigation(db: Database, job: dict, res: dict) -> dict:
    def _go(t: Tx):
        c = _check_fence(t, job, res["version"])
        report = {**res["report"], "metrics": {**res["report"]["metrics"],
                  "stages": dict(res["report"]["metrics"]["stages"])} }
        for p in res["proposals"]:
            existing = t.one("SELECT id FROM proposals WHERE case_id = ? AND action = ? AND status = 'pending'",
                             (c["id"], p["action"]))
            if existing:
                continue
            call_tool_in_tx(t, "decision", "proposal.create",
                            {"case_id": c["id"], "action": p["action"], "rationale": p["rationale"],
                             "evidence_ids": res["cited"], "case_version": c["version"]}, actor=AGENT)
        watch = _measured_stage(report["metrics"]["stages"], "Monitor", lambda:
            call_tool_in_tx(t, "monitor", "watch.schedule", {"case_id": c["id"]}, actor=AGENT))
        report["metrics"]["stages"]["Monitor"]["tool_calls"] = 1
        _measured_stage(report["metrics"]["stages"], "Reporter", lambda:
            call_tool_in_tx(t, "reporter", "report.record", {"case_id": c["id"], "report": report}, actor=AGENT))
        report["metrics"]["stages"]["Reporter"]["tool_calls"] = 1
        report["metrics"]["duration_ms"] = int(
            (time.monotonic() - report["metrics"].pop("started_monotonic")) * 1000)
        v = c["version"] + 1
        t.execute("UPDATE cases SET report = ?, version = ?, updated_ms = ? WHERE id = ?",
                  (dumps(report), v, clock.now_ms(), c["id"]))
        append_event(t, case_id=c["id"], payment_id=c["payment_id"], type="investigation_completed", actor=AGENT,
                     case_version=v, data={"verdict": report["verdict"], "confidence": report["confidence"],
                                           "proposals": [p["action"] for p in res["proposals"]],
                                           "watch": watch.get("watch_id")}, evidence_ids=res["cited"])
        complete(t, job)
        return {"case_id": c["id"], "case_version": v}
    out = db.write(_go)
    _auto_apply(out["case_id"])
    return out


def _auto_apply(case_id: str) -> None:
    """Tier 1 lets the agent apply guarded reversible proposals; Tier 0 only reports."""
    if settings.soc_tier < 1 or settings.soc_kill_switch:
        return
    db = get_db()
    props = db.read(lambda t: t.all("SELECT * FROM proposals WHERE case_id = ? AND status = 'pending' AND tier <= ?"
                                    " AND action = 'place_hold'", (case_id, settings.soc_tier)))
    for p in props:
        ver = db.read(lambda t: t.scalar("SELECT version FROM cases WHERE id = ?", (case_id,)))
        try:
            actions.apply(actor=AGENT, role="agent", case_id=case_id, action=p["action"], expected_version=ver,
                          rationale=p["rationale"], via="agent", proposal_id=p["id"],
                          command_key=f"auto:{p['id']}")
        except Exception as e:  # noqa: BLE001
            log.info("auto-apply skipped: %s", e)


def watch_check(db: Database, job: dict) -> dict:
    def _go(t: Tx):
        c = _check_fence(t, job, None)
        w = t.one("SELECT * FROM watches WHERE case_id = ?", (c["id"],))
        if not w or w["status"] != "active":
            complete(t, job)
            return {"skipped": True}
        now = clock.now_ms()
        payment = t.one("SELECT account_id, direction FROM payments WHERE id = ?", (c["payment_id"],))
        if payment["direction"] == "incoming":
            target = "s.account_id = ? AND s.counterparty_id != ?"
            parties = (payment["account_id"], w["counterparty_id"])
        else:
            target = "s.counterparty_id = ? AND s.owner_id != ?"
            parties = (w["counterparty_id"], c["owner_id"])
        new = t.all("SELECT s.payment_id FROM settlements s JOIN payments p ON p.id = s.payment_id"
                    f" WHERE {target} AND p.direction = ? AND s.created_ms > ? AND s.created_ms <= ? ORDER BY s.created_ms",
                    (*parties, payment["direction"], w["cursor_ms"], now))
        checks = w["checks"] + 1
        nxt = w["next_due_ms"] + w["interval_ms"]
        status = "done" if nxt > w["horizon_ms"] else "active"
        result = {"checked_ms": now, "new_inbound": len(new), "payment_ids": [n["payment_id"] for n in new][:20]}
        t.execute("UPDATE watches SET checks = ?, next_due_ms = ?, cursor_ms = ?, status = ?, last_result = ? WHERE id = ?",
                  (checks, nxt, now, status, dumps(result), w["id"]))
        v = c["version"] + 1
        new_case_state = c["state"]
        if new and c["state"] in ("closed", "monitoring"):
            new_case_state = "open"
        t.execute("UPDATE cases SET version = ?, updated_ms = ?, state = ? WHERE id = ?", (v, now, new_case_state, c["id"]))
        append_event(t, case_id=c["id"], payment_id=c["payment_id"],
                     type="watch_alert" if new else "watch_checked", actor=AGENT, case_version=v,
                     prev_state=c["state"], new_state=new_case_state, data={**result, "watch_status": status})
        if new:
            enqueue(t, case_id=c["id"], kind="investigate", case_version=v, trigger_key=f"investigate:{c['id']}:{v}")
        complete(t, job)
        return result
    return db.write(_go)


def schedule_due_watches(db: Database) -> int:
    now = clock.now_ms()
    def _go(t: Tx):
        rows = t.all("SELECT w.id, w.case_id, w.checks, c.version FROM watches w JOIN cases c ON c.id = w.case_id"
                     " WHERE w.status = 'active' AND w.next_due_ms <= ? LIMIT 50", (now,))
        n = 0
        for r in rows:
            if enqueue(t, case_id=r["case_id"], kind="watch_check", case_version=r["version"],
                       trigger_key=f"watch:{r['id']}:{r['checks']}"):
                n += 1
        return n
    return db.write(_go)


def process(db: Database, job: dict) -> Any:
    def run():
        if job["kind"] in ("investigate", "refresh_report"):
            return commit_investigation(db, job, investigate(job))
        if job["kind"] == "watch_check":
            return watch_check(db, job)
        raise RuntimeError(f"unknown job kind {job['kind']}")
    return _agent_span("SOC investigation", run)


def run_once(db: Database, worker_id: str) -> bool:
    job = claim(db, worker_id)
    if not job:
        return False
    try:
        process(db, job)
    except FenceLost as e:
        log.info("job %s fenced: %s", job["id"], e)
        if str(e) == "case version changed":
            _retry(db, job, str(e), count_attempt=False)
    except ToolError as e:
        _retry(db, job, f"tool:{e}")
    except Exception as e:  # noqa: BLE001
        log.warning("job %s failed: %s", job["id"], type(e).__name__)
        _retry(db, job, f"{type(e).__name__}: {e}")
    return True


class Worker(threading.Thread):
    def __init__(self, db: Database, idx: int, poll: float = 0.25):
        super().__init__(daemon=True, name=f"soc-worker-{idx}")
        self.db = db
        self.worker_id = f"{os.getpid()}-{idx}"
        self.poll = poll
        self.stop_evt = threading.Event()

    def run(self) -> None:
        last_watch = 0.0
        while not self.stop_evt.is_set():
            try:
                if time.monotonic() - last_watch > 5:
                    schedule_due_watches(self.db)
                    last_watch = time.monotonic()
                while run_once(self.db, self.worker_id) and not self.stop_evt.is_set():
                    pass
            except Exception as e:  # noqa: BLE001
                log.warning("worker loop: %s", e)
            self.stop_evt.wait(self.poll)
        self.db.close_thread()

    def stop(self) -> None:
        self.stop_evt.set()


def worker_health(t: Tx) -> dict:
    now = clock.now_ms()
    rows = t.all("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status")
    counts = {r["status"]: int(r["n"]) for r in rows}
    retries = t.scalar("SELECT COALESCE(SUM(CASE WHEN attempts > 1 THEN attempts - 1 ELSE 0 END), 0) FROM outbox")
    oldest = t.scalar("SELECT MIN(created_ms) FROM outbox WHERE status IN ('pending','leased')")
    return {"queued": counts.get("pending", 0), "leased": counts.get("leased", 0), "completed": counts.get("done", 0),
            "failed": counts.get("failed", 0), "retries": int(retries or 0),
            "oldest_pending_age_ms": (now - int(oldest)) if oldest else None, "measured_ms": now}


def main() -> None:
    """Standalone worker process: python -m app.soc.worker"""
    logging.basicConfig(level=logging.INFO)
    db = get_db()
    n = max(1, int(os.environ.get("TRINETRA_WORKERS", "2")))
    ws = [Worker(db, i) for i in range(n)]
    for w in ws:
        w.start()
    log.info("started %d SOC workers", n)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for w in ws:
            w.stop()


if __name__ == "__main__":
    main()
