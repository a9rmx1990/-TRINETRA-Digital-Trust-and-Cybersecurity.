"""Analyst queries: queue, case file, event replay and analytics.

All widgets share one scope, time bounds and a data watermark (the delivery cursor at
query time). Nothing is synthesized: every count comes from ledger rows.
"""
from __future__ import annotations

import statistics
from typing import Any

from .. import clock
from ..config import settings
from ..customer import active_restrictions, challenge_status, is_receipt_challenge, sender_account_id
from ..db import Tx, get_db, loads
from ..util import ApiError, format_inr, mask_ref
from .actions import ACTION_TIERS, eligible_actions
from .worker import worker_health

SORTS = {"priority": "c.priority ASC, c.created_ms ASC", "age": "c.created_ms ASC", "updated": "c.updated_ms DESC",
         "amount": "p.amount_minor DESC", "severity": "c.priority ASC, c.updated_ms DESC"}
OPEN_STATES = ("open",)


def watermark(t: Tx) -> dict:
    return {"cursor": int(t.scalar("SELECT value FROM delivery_counter WHERE id = 1") or 0), "as_of_ms": clock.now_ms()}


def _bounds(frm: int | None, to: int | None) -> tuple[int, int]:
    now = clock.now_ms()
    to = to or now
    frm = frm if frm is not None else to - 7 * clock.DAY
    if frm >= to:
        raise ApiError(422, "invalid_range", "Start of range must be before end.")
    if to - frm > 366 * clock.DAY:
        raise ApiError(422, "range_too_large", "Range is limited to one year.")
    return frm, to


def queue(*, frm: int | None, to: int | None, state: str | None, severity: str | None, payment_state: str | None,
          sort: str, limit: int, offset: int) -> dict:
    frm, to = _bounds(frm, to)
    limit = max(1, min(limit, 200))
    where = ["c.scope = ?", "c.created_ms >= ?", "c.created_ms < ?"]
    args: list[Any] = [settings.analyst_scope, frm, to]
    if state == "needs_action":
        where.append("(c.state = 'open' OR EXISTS (SELECT 1 FROM proposals pr WHERE pr.case_id = c.id AND pr.status = 'pending'))")
    elif state:
        where.append("c.state = ?")
        args.append(state)
    if severity:
        where.append("c.severity = ?")
        args.append(severity)
    if payment_state:
        where.append("p.state = ?")
        args.append(payment_state)
    order = SORTS.get(sort, SORTS["priority"])

    def _go(t: Tx):
        wm = watermark(t)
        base = f" FROM cases c JOIN payments p ON p.id = c.payment_id JOIN beneficiaries b ON b.id = p.beneficiary_id WHERE {' AND '.join(where)}"
        total = int(t.scalar("SELECT COUNT(*)" + base, args))
        rows = t.all("SELECT c.id, c.state, c.severity, c.priority, c.version, c.created_ms, c.updated_ms, c.hold_active,"
                     " p.id AS payment_id, p.state AS payment_state, p.decision, p.amount_minor, p.channel, p.direction, b.account_ref,"
                     " (SELECT COUNT(*) FROM proposals pr WHERE pr.case_id = c.id AND pr.status = 'pending') AS pending_proposals"
                     + base + f" ORDER BY {order} LIMIT ? OFFSET ?", (*args, limit, offset))
        now = clock.now_ms()
        items = [{"case_id": r["id"], "state": r["state"], "severity": r["severity"], "priority": r["priority"],
                  "version": r["version"], "age_ms": now - r["created_ms"], "created_ms": r["created_ms"],
                  "updated_ms": r["updated_ms"], "payment_id": r["payment_id"], "payment_state": r["payment_state"],
                  "decision": r["decision"], "amount_minor": r["amount_minor"], "amount_display": format_inr(r["amount_minor"]),
                  "channel": r["channel"], "direction": r["direction"], "beneficiary_masked": mask_ref(r["account_ref"]),
                  "pending_proposals": int(r["pending_proposals"]), "hold_active": bool(r["hold_active"])} for r in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset, "from_ms": frm, "to_ms": to,
                "watermark": wm}
    return get_db().read(_go)


def case_file(case_id: str) -> dict:
    def _go(t: Tx):
        c = t.one("SELECT * FROM cases WHERE id = ? AND scope = ?", (case_id, settings.analyst_scope))
        if not c:
            raise ApiError(404, "case_not_found", "Case not found in your scope.")
        p = t.one("SELECT * FROM payments WHERE id = ?", (c["payment_id"],))
        b = t.one("SELECT * FROM beneficiaries WHERE id = ?", (p["beneficiary_id"],))
        acct = t.one("SELECT * FROM accounts WHERE id = ?", (p["account_id"],))
        ev = t.all("SELECT * FROM evidence WHERE payment_id = ? ORDER BY created_ms, id", (p["id"],))
        events = t.all("SELECT * FROM case_events WHERE case_id = ? ORDER BY seq", (case_id,))
        props = t.all("SELECT * FROM proposals WHERE case_id = ? ORDER BY created_ms", (case_id,))
        watch = t.one("SELECT * FROM watches WHERE case_id = ?", (case_id,))
        adj = t.all("SELECT * FROM adjudications WHERE case_id = ? ORDER BY created_ms", (case_id,))
        restr = active_restrictions(t, p["account_id"], p["counterparty_id"])
        linked = t.all("SELECT p2.id, p2.state, p2.decision, p2.direction, p2.amount_minor, p2.created_ms, p2.owner_id = ? AS same_owner"
                       " FROM payments p2 WHERE p2.counterparty_id = ? AND p2.id != ? ORDER BY p2.created_ms DESC LIMIT 25",
                       (p["owner_id"], p["counterparty_id"], p["id"]))
        settlement = t.one("SELECT id, created_ms FROM settlements WHERE payment_id = ?", (p["id"],))
        challenge = t.one("SELECT salt, status, expires_ms, attempts, max_attempts, created_ms FROM challenges WHERE payment_id = ?"
                          " ORDER BY created_ms DESC LIMIT 1", (p["id"],))
        if challenge:
            challenge["status"] = challenge_status(challenge)
            challenge["receipt_delivery"] = is_receipt_challenge(challenge)
            del challenge["salt"]
        sender_id = sender_account_id(t, p)
        elig = eligible_actions(c, p, restr, sender_id)
        customer = {"account_id": acct["id"], "account_masked": mask_ref(acct["account_ref"]),
                    "account_created_ms": acct["created_ms"], "owner_ref": p["owner_id"][-6:]}
        evidence = []
        for e in ev:
            payload = loads(e["payload"], {})
            evidence.append({"id": e["id"], "source": e["source"], "kind": e["kind"], "status": e["status"],
                             "model_id": e["model_id"], "revision": e["revision"], "score_scale": e["score_scale"],
                             "score": e["score"], "flagged": None if e["flagged"] is None else bool(e["flagged"]),
                             "review_only": bool(e["review_only"]), "created_ms": e["created_ms"], "payload": payload})
        return {
            "case": {"id": c["id"], "state": c["state"], "severity": c["severity"], "priority": c["priority"],
                     "version": c["version"], "hold_active": bool(c["hold_active"]), "verdict": c["verdict"],
                     "created_ms": c["created_ms"], "updated_ms": c["updated_ms"],
                     "first_disposition_ms": c["first_disposition_ms"], "report": loads(c["report"])},
            "payment": {"id": p["id"], "state": p["state"], "decision": p["decision"], "direction": p["direction"],
                        "policy_version": p["policy_version"],
                        "amount_minor": p["amount_minor"], "amount_display": format_inr(p["amount_minor"]),
                        "channel": p["channel"], "remark": p["remark"], "created_ms": p["created_ms"],
                        "updated_ms": p["updated_ms"], "reasons": loads(p["reasons"]), "signals": loads(p["signals"]),
                        "settlement": settlement, "challenge": challenge},
            "customer": customer,
            "sender": customer if p["direction"] == "outgoing" else {
                "account_id": sender_id, "account_masked": mask_ref(b["account_ref"]),
                "account_created_ms": None, "owner_ref": None},
            "beneficiary": {"name": b["display_name"], "masked": mask_ref(b["account_ref"]), "added_ms": b["created_ms"]},
            "restrictions": restr,
            "evidence": evidence,
            "linked_transactions": [{**l, "amount_display": format_inr(l["amount_minor"]), "same_owner": bool(l["same_owner"])}
                                    for l in linked],
            "timeline": [{"seq": e["seq"], "cursor": e["delivery_seq"], "id": e["id"], "type": e["type"], "actor": e["actor"],
                          "prev_state": e["prev_state"], "new_state": e["new_state"], "case_version": e["case_version"],
                          "data": loads(e["data"]), "evidence_ids": loads(e["evidence_ids"]), "created_ms": e["created_ms"]}
                         for e in events],
            "proposals": [{"id": r["id"], "action": r["action"], "params": loads(r["params"]), "rationale": r["rationale"],
                           "evidence_ids": loads(r["evidence_ids"]), "tier": r["tier"], "status": r["status"],
                           "case_version": r["case_version"], "created_by": r["created_by"], "created_ms": r["created_ms"],
                           "reviewed_by": r["reviewed_by"], "reviewed_ms": r["reviewed_ms"],
                           "review_rationale": r["review_rationale"]} for r in props],
            "watch": None if not watch else {k: watch[k] for k in ("id", "status", "horizon_ms", "interval_ms", "next_due_ms",
                                                                   "checks", "created_ms")} | {"last_result": loads(watch["last_result"])},
            "adjudications": adj,
            "eligible_actions": [{"action": a, "tier": ACTION_TIERS[a]} for a in elig],
            "watermark": watermark(t),
        }
    return get_db().read(_go)


def replay(after: int, limit: int = 200) -> dict:
    limit = max(1, min(limit, 500))
    def _go(t: Tx):
        rows = t.all("SELECT delivery_seq, case_id, case_version, type, created_ms FROM case_events WHERE scope = ?"
                     " AND delivery_seq > ? ORDER BY delivery_seq LIMIT ?", (settings.analyst_scope, after, limit))
        return {"notices": [{"cursor": r["delivery_seq"], "case_id": r["case_id"], "case_version": r["case_version"],
                             "event": r["type"], "created_ms": r["created_ms"]} for r in rows],
                "watermark": watermark(t)}
    return get_db().read(_go)


# ------------------------------------------------------------------ analytics
def _interval(frm: int, to: int) -> int:
    span = to - frm
    if span <= 2 * clock.DAY:
        return clock.HOUR
    if span <= 62 * clock.DAY:
        return clock.DAY
    return 7 * clock.DAY


def _pct(vals: list[int], q: float) -> int | None:
    if not vals:
        return None
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[k]


def analytics(frm: int | None, to: int | None, tz_offset_min: int = 0) -> dict:
    frm, to = _bounds(frm, to)
    step = _interval(frm, to)
    off = tz_offset_min * clock.MINUTE
    start = ((frm + off) // step) * step - off

    def _go(t: Tx):
        wm = watermark(t)
        pays = t.all("SELECT id, decision, state, created_ms FROM payments WHERE created_ms >= ? AND created_ms < ?"
                     " AND legacy_demo = 0", (frm, to))
        buckets = []
        b = start
        while b < to:
            buckets.append({"start_ms": b, "end_ms": b + step, "ALLOW": 0, "STEP_UP": 0, "HOLD": 0, "BLOCK": 0, "total": 0})
            b += step
        for p in pays:
            i = (p["created_ms"] - start) // step
            if 0 <= i < len(buckets):
                buckets[i][p["decision"]] += 1
                buckets[i]["total"] += 1
        totals = {k: sum(x[k] for x in buckets) for k in ("ALLOW", "STEP_UP", "HOLD", "BLOCK", "total")}
        current = {}
        for p in pays:
            current[p["state"]] = current.get(p["state"], 0) + 1
        intervention_rate = None if totals["total"] == 0 else round(
            (totals["STEP_UP"] + totals["HOLD"] + totals["BLOCK"]) / totals["total"], 4)

        now = clock.now_ms()
        cases = t.all("SELECT c.id, c.state, c.priority, c.created_ms, c.first_disposition_ms FROM cases c"
                      " WHERE c.scope = ? AND c.created_ms >= ? AND c.created_ms < ?", (settings.analyst_scope, frm, to))
        age_edges = [("lt_1h", 0, clock.HOUR), ("1h_4h", clock.HOUR, 4 * clock.HOUR),
                     ("4h_24h", 4 * clock.HOUR, clock.DAY), ("gt_24h", clock.DAY, None)]
        open_age = {pr: {name: 0 for name, *_ in age_edges} for pr in (1, 2, 3)}
        review_times = []
        for c in cases:
            if c["state"] == "open":
                age = now - c["created_ms"]
                for name, lo, hi in age_edges:
                    if age >= lo and (hi is None or age < hi):
                        open_age[c["priority"]][name] += 1
            if c["first_disposition_ms"]:
                review_times.append(c["first_disposition_ms"] - c["created_ms"])
        watches = t.all("SELECT status, COUNT(*) AS n FROM watches WHERE created_ms >= ? AND created_ms < ? GROUP BY status",
                        (frm, to))

        # Model quality: reviewed labels joined to stored flagged observations per signal and revision.
        adj = t.all("SELECT a.case_id, a.payment_id, a.label FROM adjudications a WHERE a.created_ms = ("
                    " SELECT MAX(a2.created_ms) FROM adjudications a2 WHERE a2.case_id = a.case_id)"
                    " AND a.created_ms >= ? AND a.created_ms < ?", (frm, to))
        quality: dict[str, dict] = {}
        for a in adj:
            evs = t.all("SELECT kind, model_id, revision, flagged, status FROM evidence WHERE payment_id = ? AND source = 'signal'",
                        (a["payment_id"],))
            for e in evs:
                if e["flagged"] is None:
                    key = f"{e['kind']}|unscored"
                    q = quality.setdefault(key, {"signal": e["kind"], "model_id": e["model_id"], "revision": e["revision"],
                                                 "tp": 0, "fp": 0, "tn": 0, "fn": 0, "abstain": 0})
                    q["abstain"] += 1
                    continue
                key = f"{e['kind']}|{e['model_id']}|{e['revision']}"
                q = quality.setdefault(key, {"signal": e["kind"], "model_id": e["model_id"], "revision": e["revision"],
                                             "tp": 0, "fp": 0, "tn": 0, "fn": 0, "abstain": 0})
                fraud = a["label"] == "fraud"
                flg = bool(e["flagged"])
                q["tp" if fraud and flg else "fp" if flg else "fn" if fraud else "tn"] += 1
        qrows = []
        for q in quality.values():
            n = q["tp"] + q["fp"] + q["tn"] + q["fn"]
            q["n"] = n
            q["precision"] = None if q["tp"] + q["fp"] == 0 else round(q["tp"] / (q["tp"] + q["fp"]), 3)
            q["recall"] = None if q["tp"] + q["fn"] == 0 else round(q["tp"] / (q["tp"] + q["fn"]), 3)
            qrows.append(q)

        return {
            "from_ms": frm, "to_ms": to, "interval_ms": step, "tz_offset_min": tz_offset_min, "watermark": wm,
            "volume": {"buckets": buckets, "totals": totals, "current_state": current,
                       "intervention_rate": intervention_rate},
            "queue": {"open_by_priority_age": open_age, "open_total": sum(sum(v.values()) for v in open_age.values()),
                      "review_time": {"n": len(review_times), "p50_ms": _pct(review_times, 0.5),
                                      "p90_ms": _pct(review_times, 0.9),
                                      "mean_ms": int(statistics.mean(review_times)) if review_times else None},
                      "watches": {r["status"]: int(r["n"]) for r in watches}},
            "model_quality": {"adjudicated_cases": len(adj), "rows": sorted(qrows, key=lambda r: (r["signal"], str(r["revision"])))},
            "worker": worker_health(t),
        }
    return get_db().read(_go)


def bucket_rows(frm: int, to: int, decision: str | None) -> dict:
    def _go(t: Tx):
        q = "SELECT p.id, p.decision, p.state, p.amount_minor, p.channel, p.created_ms, c.id AS case_id FROM payments p" \
            " LEFT JOIN cases c ON c.payment_id = p.id WHERE p.created_ms >= ? AND p.created_ms < ? AND p.legacy_demo = 0"
        args: list[Any] = [frm, to]
        if decision:
            q += " AND p.decision = ?"
            args.append(decision)
        rows = t.all(q + " ORDER BY p.created_ms LIMIT 500", args)
        return {"items": [{**r, "amount_display": format_inr(r["amount_minor"])} for r in rows],
                "watermark": watermark(t)}
    return get_db().read(_go)
