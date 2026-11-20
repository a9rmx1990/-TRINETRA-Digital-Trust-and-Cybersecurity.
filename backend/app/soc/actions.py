"""Guarded action service.

Every state-changing SOC command is version-checked against the case, rechecks
authorization, scope, eligibility, tier, rate limit and the kill switch, and writes
an audit record whether it succeeds or not. Retried commands with the same command key
return the recorded outcome instead of acting twice.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .. import clock
from ..config import settings
from ..customer import active_restrictions, issue_challenge, sender_account_id, settle
from ..db import Tx, dumps, get_db, loads
from ..events import append_event, enqueue, publish_hints
from ..util import ApiError, new_id, sha256

# Tier 1: guarded, reversible. Tier 2: high impact, always needs human approval when proposed by the agent.
ACTION_TIERS = {
    "issue_challenge": 1,
    "verify_incoming": 2,
    "place_hold": 1,
    "release": 2,
    "reject_transfer": 2,
    "restrict_counterparty": 2,
    "restrict_sender_account": 2,
    "lift_restriction": 2,
    "record_verdict": 2,
    "close_case": 1,
    "reopen_case": 1,
}
TERMINAL = {"SETTLED", "BLOCKED", "REJECTED"}
DISPOSITION_ACTIONS = {"issue_challenge", "verify_incoming", "release", "reject_transfer", "restrict_counterparty",
                       "restrict_sender_account", "record_verdict", "close_case"}

_rate: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()


def _rate_check(actor: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        q = _rate[actor]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.soc_action_rate_per_min:
            raise ApiError(429, "rate_limited", "Too many actions in the last minute. Wait and retry.")
        q.append(now)


def _audit(t: Tx, case_id: str | None, actor: str, role: str, action: str, args: dict, outcome: str) -> None:
    safe = {k: v for k, v in args.items() if k not in ("rationale",)}
    t.execute("INSERT INTO tool_audit(id, case_id, actor, role, tool, args, outcome, created_ms) VALUES (?,?,?,?,?,?,?,?)",
              (new_id("aud"), case_id, actor, role, f"action.{action}", dumps(safe), outcome, clock.now_ms()))


def eligible_actions(case: dict, payment: dict, restrictions: list[dict], sender_id: str | None) -> list[str]:
    s = payment["state"]
    out = []
    if s == "VERIFICATION_REQUIRED" and not restrictions:
        if payment["direction"] == "outgoing":
            out.append("issue_challenge")
        elif not case["hold_active"]:
            out.append("verify_incoming")
    if s == "VERIFICATION_REQUIRED" and not case["hold_active"]:
        out.append("place_hold")
    if s == "HELD" or (s == "VERIFICATION_REQUIRED" and case["hold_active"]):
        out.append("release")
    if s in ("HELD", "VERIFICATION_REQUIRED"):
        out.append("reject_transfer")
    if not any(r["scope_type"] == "counterparty" for r in restrictions):
        out.append("restrict_counterparty")
    if sender_id and not any(r["scope_type"] == "account" and r["scope_id"] == sender_id for r in restrictions):
        out.append("restrict_sender_account")
    if restrictions:
        out.append("lift_restriction")
    out.append("record_verdict")
    if case["state"] != "closed":
        out.append("close_case")
    else:
        out.append("reopen_case")
    return out


def apply(*, actor: str, role: str, case_id: str, action: str, expected_version: int, rationale: str,
          params: dict | None = None, command_key: str | None = None, via: str = "analyst",
          proposal_id: str | None = None, deliver_to_receipt: bool = False) -> dict:
    params = params or {}
    db = get_db()
    args = {"action": action, "expected_version": expected_version, "params": params, "proposal_id": proposal_id}
    if deliver_to_receipt:
        args["delivery"] = "sandbox_receipt"
    try:
        if action not in ACTION_TIERS:
            raise ApiError(422, "unknown_action", "Unknown action.")
        if action == "verify_incoming" and (via != "analyst_workspace" or role != "analyst"):
            raise ApiError(403, "analyst_workspace_required", "Verify this request from the Gemini analyst workspace.")
        if via == "agent":
            if settings.soc_kill_switch:
                raise ApiError(423, "kill_switch", "Automated SOC actions are disabled by the kill switch.")
            if ACTION_TIERS[action] >= 2 or ACTION_TIERS[action] > settings.soc_tier:
                raise ApiError(403, "tier_denied", "This action needs human approval at the current tier.")
        if not rationale or len(rationale.strip()) < 8:
            raise ApiError(422, "rationale_required", "Enter a rationale of at least 8 characters.")
        _rate_check(actor)
        fp = sha256(dumps({"case_id": case_id, **args}))
        result = db.write(lambda t: _apply_tx(t, actor, role, case_id, action, expected_version, rationale.strip(),
                                              params, command_key, fp, proposal_id, deliver_to_receipt))
    except ApiError as e:
        detail = e.detail if isinstance(e.detail, dict) else {"code": "error"}
        db.write(lambda t: _audit(t, case_id, actor, role, action, args, f"denied:{detail.get('code')}"))
        raise
    publish_hints()
    return result


def _apply_tx(t: Tx, actor, role, case_id, action, expected_version, rationale, params, command_key, fp, proposal_id,
              deliver_to_receipt):
    if command_key:
        prior = t.one("SELECT * FROM command_results WHERE command_key = ?", (command_key,))
        if prior:
            if prior["fingerprint"] != fp:
                raise ApiError(409, "command_key_conflict", "This command key was used for a different action.")
            return {**loads(prior["result"]), "replayed": True}
    t.lock_rows("cases", [case_id])
    case = t.one("SELECT * FROM cases WHERE id = ? AND scope = ?", (case_id, settings.analyst_scope))
    if not case:
        raise ApiError(404, "case_not_found", "Case not found in your scope.")
    if case["version"] != expected_version:
        raise ApiError(409, "stale_version", "This case changed since you opened it. Refresh to continue.",
                       current_version=case["version"])
    t.lock_rows("payments", [case["payment_id"]])
    p = t.one("SELECT * FROM payments WHERE id = ?", (case["payment_id"],))
    sender_id = sender_account_id(t, p)
    if action == "verify_incoming":
        accounts = {p["account_id"]}
        if sender_id:
            accounts.add(sender_id)
        t.lock_keys(f"restriction:counterparty:{p['counterparty_id']}",
                    *(f"restriction:account:{account_id}" for account_id in accounts))
    restr = active_restrictions(t, p["account_id"], p["counterparty_id"])
    if action not in eligible_actions(case, p, restr, sender_id):
        raise ApiError(409, "not_eligible", "That action is not available for the current case state.")

    now = clock.now_ms()
    prev_state = p["state"]
    out: dict = {"action": action}
    pay_state = p["state"]
    case_updates: dict = {}

    if action == "verify_incoming":
        run_id = params.get("analysis_run_id")
        if not t.scalar("SELECT 1 FROM analyst_workspace_runs WHERE id = ? AND case_id = ? AND case_version = ?",
                        (run_id, case_id, expected_version)):
            raise ApiError(409, "analysis_required", "Run or refresh the current case analysis before verifying.")
        pay_state = "SETTLED"
        settle(t, p)
        t.execute("UPDATE challenges SET status = 'revoked' WHERE payment_id = ? AND status = 'active'", (p["id"],))
        t.execute("UPDATE proposals SET status = 'superseded', reviewed_by = ?, reviewed_ms = ?, review_rationale = ?"
                  " WHERE case_id = ? AND action = 'issue_challenge' AND status = 'pending'", (actor, now, rationale, case_id))
    elif action == "issue_challenge":
        code, meta = issue_challenge(t, p, actor, deliver_to_receipt=deliver_to_receipt)
        out.update(meta)
        if deliver_to_receipt:
            out["delivery"] = "sandbox_receipt"
            if not proposal_id:
                proposal_id = t.scalar("SELECT id FROM proposals WHERE case_id = ? AND action = 'issue_challenge'"
                                       " AND status = 'pending' ORDER BY created_ms LIMIT 1", (case_id,))
        else:
            out["code"] = code  # shown once to the legacy API caller, never stored in clear
    elif action == "place_hold":
        case_updates["hold_active"] = 1
    elif action == "release":
        if restr:
            raise ApiError(409, "restricted", "An active restriction prevents release.")
        case_updates["hold_active"] = 0
        if p["state"] == "HELD":
            pay_state = "SETTLED"
            settle(t, p)
    elif action == "reject_transfer":
        pay_state = "REJECTED"
        case_updates["hold_active"] = 0
        t.execute("UPDATE challenges SET status = 'revoked' WHERE payment_id = ? AND status = 'active'", (p["id"],))
    elif action in ("restrict_counterparty", "restrict_sender_account"):
        scope_type, scope_id = (("counterparty", p["counterparty_id"]) if action == "restrict_counterparty"
                                else ("account", sender_id))
        t.lock_keys(f"restriction:{scope_type}:{scope_id}")
        if not t.one("SELECT id FROM restrictions WHERE scope_type = ? AND scope_id = ? AND active = 1", (scope_type, scope_id)):
            rid = new_id("rst")
            t.execute("INSERT INTO restrictions(id, scope_type, scope_id, reason, active, created_by, created_ms, case_id)"
                      " VALUES (?,?,?,?,1,?,?,?)", (rid, scope_type, scope_id, rationale[:300], actor, now, case_id))
            out["restriction_id"] = rid
        if p["state"] not in TERMINAL:
            pay_state = "BLOCKED"
            t.execute("UPDATE challenges SET status = 'revoked' WHERE payment_id = ? AND status = 'active'", (p["id"],))
    elif action == "lift_restriction":
        rid = params.get("restriction_id")
        if not rid or rid not in {r["id"] for r in restr}:
            raise ApiError(422, "restriction_not_found", "Choose an active restriction linked to this case.")
        t.execute("UPDATE restrictions SET active = 0, lifted_ms = ? WHERE id = ? AND active = 1", (now, rid))
    elif action == "record_verdict":
        label = params.get("label")
        if label not in ("fraud", "legitimate"):
            raise ApiError(422, "invalid_label", "Choose fraud or legitimate.")
        prev = t.one("SELECT id, label FROM adjudications WHERE case_id = ? ORDER BY created_ms DESC LIMIT 1", (case_id,))
        aid = new_id("adj")
        t.execute("INSERT INTO adjudications(id, case_id, payment_id, label, reviewer, rationale, supersedes, created_ms)"
                  " VALUES (?,?,?,?,?,?,?,?)", (aid, case_id, p["id"], label, actor, rationale, prev["id"] if prev else None, now))
        case_updates["verdict"] = label
        case_updates["verdict_source"] = "analyst"
        out.update({"adjudication_id": aid, "override_of": prev["label"] if prev else None})
    elif action == "close_case":
        w = t.one("SELECT status FROM watches WHERE case_id = ?", (case_id,))
        case_updates["state"] = "monitoring" if w and w["status"] == "active" else "closed"
        case_updates["closed_ms"] = now
    elif action == "reopen_case":
        case_updates["state"] = "open"

    if pay_state != p["state"]:
        if t.rowcount("UPDATE payments SET state = ?, version = version + 1, updated_ms = ? WHERE id = ? AND state = ?",
                      (pay_state, now, p["id"], p["state"])) != 1:
            raise ApiError(409, "stale_version", "Payment changed concurrently. Refresh to continue.")
    new_version = case["version"] + 1
    sets = {"version": new_version, "updated_ms": now, **case_updates}
    if action in DISPOSITION_ACTIONS and not case["first_disposition_ms"]:
        sets["first_disposition_ms"] = now
    cols = ", ".join(f"{k} = ?" for k in sets)
    t.execute(f"UPDATE cases SET {cols} WHERE id = ?", (*sets.values(), case_id))
    if proposal_id:
        t.execute("UPDATE proposals SET status = 'applied', reviewed_by = ?, reviewed_ms = ?, review_rationale = ?"
                  " WHERE id = ? AND status = 'pending'", (actor, now, rationale, proposal_id))
    ev_type = "verdict_override" if action == "record_verdict" and out.get("override_of") else f"action_{action}"
    append_event(t, case_id=case_id, payment_id=p["id"], type=ev_type, actor=actor, case_version=new_version,
                 prev_state=prev_state, new_state=pay_state,
                 data={"rationale": rationale, "params": {k: v for k, v in params.items()},
                       "proposal_id": proposal_id, **{k: v for k, v in out.items() if k != "code"}})
    if action in ("reopen_case",) or (action == "record_verdict"):
        enqueue(t, case_id=case_id, kind="refresh_report", case_version=new_version,
                trigger_key=f"refresh:{case_id}:{new_version}")
    _audit(t, case_id, actor, role, action, {"expected_version": expected_version, "params": params}, "applied")
    result = {**out, "case_version": new_version, "payment_state": pay_state}
    if command_key:
        stored = {k: v for k, v in result.items() if k != "code"}
        if "code" in result:
            stored["code_note"] = "The code was shown once. Issue a new challenge if it was lost."
        t.execute("INSERT INTO command_results(command_key, actor, fingerprint, result, created_ms) VALUES (?,?,?,?,?)",
                  (command_key, actor, fp, dumps(stored), now))
    return result


def review_proposal(*, actor: str, proposal_id: str, decision: str, expected_version: int, rationale: str,
                    command_key: str | None = None) -> dict:
    db = get_db()
    prop = db.read(lambda t: t.one("SELECT * FROM proposals WHERE id = ?", (proposal_id,)))
    if not prop:
        raise ApiError(404, "proposal_not_found", "Proposal not found.")
    case = db.read(lambda t: t.one("SELECT scope FROM cases WHERE id = ?", (prop["case_id"],)))
    if not case or case["scope"] != settings.analyst_scope:
        raise ApiError(404, "proposal_not_found", "Proposal not found.")
    if prop["status"] != "pending":
        raise ApiError(409, "proposal_not_pending", f"Proposal already {prop['status']}.")
    if decision == "approve":
        return apply(actor=actor, role="analyst", case_id=prop["case_id"], action=prop["action"],
                     expected_version=expected_version, rationale=rationale, params=loads(prop["params"]),
                     command_key=command_key, proposal_id=proposal_id)
    if decision != "reject":
        raise ApiError(422, "invalid_decision", "Choose approve or reject.")
    if not rationale or len(rationale.strip()) < 8:
        raise ApiError(422, "rationale_required", "Enter a rationale of at least 8 characters.")

    def _go(t: Tx):
        t.lock_rows("cases", [prop["case_id"]])
        c = t.one("SELECT * FROM cases WHERE id = ?", (prop["case_id"],))
        if c["version"] != expected_version:
            raise ApiError(409, "stale_version", "This case changed since you opened it. Refresh to continue.",
                           current_version=c["version"])
        if t.rowcount("UPDATE proposals SET status = 'rejected', reviewed_by = ?, reviewed_ms = ?, review_rationale = ?"
                      " WHERE id = ? AND status = 'pending'", (actor, clock.now_ms(), rationale.strip(), proposal_id)) != 1:
            raise ApiError(409, "proposal_not_pending", "Proposal was already reviewed.")
        v = c["version"] + 1
        t.execute("UPDATE cases SET version = ?, updated_ms = ? WHERE id = ?", (v, clock.now_ms(), c["id"]))
        append_event(t, case_id=c["id"], payment_id=c["payment_id"], type="proposal_rejected", actor=actor,
                     case_version=v, data={"proposal_id": proposal_id, "action": prop["action"], "rationale": rationale})
        _audit(t, c["id"], actor, "analyst", "review_proposal", {"proposal_id": proposal_id, "decision": "reject"}, "applied")
        return {"proposal_id": proposal_id, "status": "rejected", "case_version": v}
    return db.write(_go)
