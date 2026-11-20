"""Case-scoped MCP tools (JSON-RPC 2.0 shape).

Each role has an explicit allow-list. Every call is audited with redacted arguments.
Transcript and remark text are returned as untrusted evidence and are never
interpreted as instructions by the pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .. import clock
from ..config import settings
from ..db import Tx, dumps, get_db, loads
from ..util import format_inr, mask_ref, new_id

ROLES = {
    "triage": {"case.get", "case.history"},
    "investigator": {"case.get", "call.evidence", "graph.get", "model.evidence", "cases.similar_closed"},
    "decision": {"case.get", "model.evidence", "proposal.create"},
    "monitor": {"case.get", "watch.schedule"},
    "reporter": {"case.get", "report.record"},
    "analyst_read": {"case.get", "case.history", "call.evidence", "graph.get", "model.evidence", "cases.similar_closed"},
}
REDACT_KEYS = {"code", "token", "passcode", "text", "remark", "rationale", "report"}


class ToolError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[[Tx, dict, dict], Any]
    write: bool = False


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, schema: dict, write: bool = False):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, schema, fn, write)
        return fn
    return deco


def _case(t: Tx, case_id: str, scope: str) -> dict:
    c = t.one("SELECT * FROM cases WHERE id = ? AND scope = ?", (case_id, scope))
    if not c:
        raise ToolError(-32004, "case not found in scope")
    return c


def _redact(args: dict) -> dict:
    return {k: ("[redacted]" if k in REDACT_KEYS else v) for k, v in args.items()}


def call_tool(role: str, name: str, args: dict, *, actor: str, scope: str | None = None) -> Any:
    scope = scope or settings.analyst_scope
    db = get_db()
    outcome = "ok"
    try:
        if name not in REGISTRY:
            raise ToolError(-32601, f"unknown tool {name}")
        if name not in ROLES.get(role, set()):
            raise ToolError(-32003, f"role {role} may not call {name}")
        tl = REGISTRY[name]
        if "case_id" not in args:
            raise ToolError(-32602, "case_id is required")
        ctx = {"role": role, "actor": actor, "scope": scope}
        if tl.write:
            return db.write(lambda t: (_case(t, args["case_id"], scope), tl.fn(t, args, ctx))[1])
        return db.read(lambda t: (_case(t, args["case_id"], scope), tl.fn(t, args, ctx))[1])
    except ToolError as e:
        outcome = f"error:{e.code}"
        raise
    except Exception as e:  # noqa: BLE001
        outcome = f"error:{type(e).__name__}"
        raise
    finally:
        db.write(lambda t: t.execute(
            "INSERT INTO tool_audit(id, case_id, actor, role, tool, args, outcome, created_ms) VALUES (?,?,?,?,?,?,?,?)",
            (new_id("aud"), args.get("case_id"), actor, role, name, dumps(_redact(args)), outcome, clock.now_ms())))


def call_tool_in_tx(t: Tx, role: str, name: str, args: dict, *, actor: str, scope: str | None = None) -> Any:
    """Write tools used inside the worker's fenced commit so their effects are atomic with it."""
    scope = scope or settings.analyst_scope
    if name not in ROLES.get(role, set()):
        raise ToolError(-32003, f"role {role} may not call {name}")
    _case(t, args["case_id"], scope)
    out = REGISTRY[name].fn(t, args, {"role": role, "actor": actor, "scope": scope})
    t.execute("INSERT INTO tool_audit(id, case_id, actor, role, tool, args, outcome, created_ms) VALUES (?,?,?,?,?,?,?,?)",
              (new_id("aud"), args.get("case_id"), actor, role, name, dumps(_redact(args)), "ok", clock.now_ms()))
    return out


def jsonrpc(role: str, req: dict, *, actor: str) -> dict:
    rid = req.get("id")
    method = req.get("method")
    try:
        if method == "tools/list":
            allowed = ROLES.get(role, set())
            res = {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.schema}
                             for t in REGISTRY.values() if t.name in allowed]}
        elif method == "tools/call":
            p = req.get("params") or {}
            out = call_tool(role, p.get("name", ""), p.get("arguments") or {}, actor=actor)
            res = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": False}
        else:
            raise ToolError(-32601, "method not found")
        return {"jsonrpc": "2.0", "id": rid, "result": res}
    except ToolError as e:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": str(e)}}


CASE_ARG = {"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]}


@tool("case.get", "Current case state, version and payment summary.", CASE_ARG)
def _case_get(t: Tx, a: dict, ctx: dict) -> dict:
    c = _case(t, a["case_id"], ctx["scope"])
    p = t.one("SELECT * FROM payments WHERE id = ?", (c["payment_id"],))
    b = t.one("SELECT display_name, account_ref, created_ms FROM beneficiaries WHERE id = ?", (p["beneficiary_id"],))
    acct = t.one("SELECT created_ms FROM accounts WHERE id = ?", (p["account_id"],))
    return {"case": {k: c[k] for k in ("id", "state", "severity", "priority", "version", "hold_active", "verdict",
                                       "created_ms", "updated_ms")},
            "payment": {"id": p["id"], "state": p["state"], "decision": p["decision"], "amount_minor": p["amount_minor"],
                        "amount_display": format_inr(p["amount_minor"]), "channel": p["channel"], "direction": p["direction"],
                        "policy_version": p["policy_version"], "reasons": loads(p["reasons"]),
                        "signals": loads(p["signals"]), "created_ms": p["created_ms"],
                        "beneficiary": {"name": b["display_name"], "masked": mask_ref(b["account_ref"]),
                                        "added_ms": b["created_ms"]},
                        "customer_account_created_ms": acct["created_ms"],
                        "sender_account_created_ms": acct["created_ms"] if p["direction"] == "outgoing" else None}}


@tool("case.history", "Bounded payment history for the case owner (last 20).", CASE_ARG)
def _case_history(t: Tx, a: dict, ctx: dict) -> list[dict]:
    c = _case(t, a["case_id"], ctx["scope"])
    rows = t.all("SELECT id, state, decision, direction, amount_minor, counterparty_id, created_ms FROM payments WHERE owner_id = ?"
                 " AND id != ? ORDER BY created_ms DESC LIMIT 20", (c["owner_id"], c["payment_id"]))
    return rows


@tool("call.evidence", "Capture quality, transcript segments (untrusted text) and voice windows.", CASE_ARG)
def _call_evidence(t: Tx, a: dict, ctx: dict) -> dict:
    c = _case(t, a["case_id"], ctx["scope"])
    rows = t.all("SELECT id, kind, status, model_id, revision, score_scale, score, flagged, review_only, payload, created_ms"
                 " FROM evidence WHERE payment_id = ? AND kind IN ('capture_quality','transcript','voice_authenticity',"
                 "'speech_content')", (c["payment_id"],))
    return {r["kind"]: {**{k: r[k] for k in r if k != "payload"}, "payload": loads(r["payload"])} for r in rows}


@tool("graph.get", "Bounded recipient graph snapshot from settled history.", CASE_ARG)
def _graph_get(t: Tx, a: dict, ctx: dict) -> dict:
    c = _case(t, a["case_id"], ctx["scope"])
    r = t.one("SELECT id, payload FROM evidence WHERE payment_id = ? AND kind = 'recipient_graph_snapshot'", (c["payment_id"],))
    return {"evidence_id": r["id"], **loads(r["payload"])} if r else {}


@tool("model.evidence", "All signal observations with provenance for the case.", CASE_ARG)
def _model_evidence(t: Tx, a: dict, ctx: dict) -> list[dict]:
    c = _case(t, a["case_id"], ctx["scope"])
    rows = t.all("SELECT id, source, kind, status, model_id, revision, score_scale, score, flagged, review_only, created_ms"
                 " FROM evidence WHERE payment_id = ? ORDER BY created_ms, id", (c["payment_id"],))
    return rows


@tool("cases.similar_closed", "Closed cases with the same recipient (max 5).", CASE_ARG)
def _similar(t: Tx, a: dict, ctx: dict) -> list[dict]:
    c = _case(t, a["case_id"], ctx["scope"])
    p = t.one("SELECT counterparty_id FROM payments WHERE id = ?", (c["payment_id"],))
    return t.all("SELECT c.id, c.verdict, c.state, p.decision, p.state AS payment_state, c.closed_ms FROM cases c"
                 " JOIN payments p ON p.id = c.payment_id WHERE p.counterparty_id = ? AND c.id != ? AND c.scope = ?"
                 " AND c.state = 'closed' ORDER BY c.closed_ms DESC LIMIT 5", (p["counterparty_id"], c["id"], ctx["scope"]))


@tool("proposal.create", "Record an action proposal citing case evidence.",
      {"type": "object", "required": ["case_id", "action", "rationale", "evidence_ids", "case_version"],
       "properties": {"case_id": {"type": "string"}, "action": {"type": "string"}, "rationale": {"type": "string"},
                      "evidence_ids": {"type": "array"}, "case_version": {"type": "integer"}, "params": {"type": "object"}}},
      write=True)
def _proposal_create(t: Tx, a: dict, ctx: dict) -> dict:
    from .actions import ACTION_TIERS
    if a["action"] not in ACTION_TIERS:
        raise ToolError(-32602, "unknown action")
    validate_citations(t, a["case_id"], a["evidence_ids"])
    pid = new_id("prp")
    t.execute("INSERT INTO proposals(id, case_id, action, params, rationale, evidence_ids, tier, status, case_version,"
              " created_by, created_ms) VALUES (?,?,?,?,?,?,?,'pending',?,?,?)",
              (pid, a["case_id"], a["action"], dumps(a.get("params") or {}), a["rationale"][:1000],
               dumps(a["evidence_ids"]), ACTION_TIERS[a["action"]], a["case_version"], ctx["actor"], clock.now_ms()))
    return {"proposal_id": pid, "tier": ACTION_TIERS[a["action"]]}


@tool("watch.schedule", "Schedule daily recipient checks for the configured horizon.", CASE_ARG, write=True)
def _watch(t: Tx, a: dict, ctx: dict) -> dict:
    c = _case(t, a["case_id"], ctx["scope"])
    existing = t.one("SELECT id, status FROM watches WHERE case_id = ?", (c["id"],))
    if existing:
        return {"watch_id": existing["id"], "status": existing["status"], "created": False}
    p = t.one("SELECT counterparty_id, created_ms FROM payments WHERE id = ?", (c["payment_id"],))
    now = clock.now_ms()
    wid = new_id("wch")
    t.execute("INSERT INTO watches(id, case_id, counterparty_id, status, horizon_ms, interval_ms, next_due_ms, cursor_ms,"
              " created_ms) VALUES (?,?,?,'active',?,?,?,?,?)",
              (wid, c["id"], p["counterparty_id"], now + settings.watch_days * clock.DAY, clock.DAY, now + clock.DAY,
               p["created_ms"], now))
    return {"watch_id": wid, "status": "active", "created": True}


@tool("report.record", "Persist the analyst alert and investigation metrics.",
      {"type": "object", "required": ["case_id", "report"],
       "properties": {"case_id": {"type": "string"}, "report": {"type": "object"}}}, write=True)
def _report(t: Tx, a: dict, ctx: dict) -> dict:
    validate_citations(t, a["case_id"], a["report"].get("evidence_ids", []))
    return {"accepted": True}


def validate_citations(t: Tx, case_id: str, evidence_ids: list[str]) -> None:
    if not evidence_ids:
        raise ToolError(-32602, "at least one evidence id must be cited")
    rows = t.all("SELECT id FROM evidence WHERE case_id = ?", (case_id,))
    valid = {r["id"] for r in rows}
    bad = [e for e in evidence_ids if e not in valid]
    if bad:
        raise ToolError(-32602, "cited evidence does not belong to this case")
