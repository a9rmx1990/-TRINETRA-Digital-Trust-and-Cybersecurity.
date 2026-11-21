"""Explainable review signals for sandbox transfers and settled activity."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean

from . import clock
from .config import settings
from .db import Tx, dumps, loads
from .util import new_id

PATTERN = "COMMON_BENEFICIARY_PATTERN"


@dataclass(frozen=True)
class Rules:
    version: str = "sandbox-1"
    weights: tuple[int, ...] = (20, 20, 15, 10, 15, 20)
    bands: tuple[int, int, int] = (25, 50, 75)
    alert_score: int = 50
    history_days: int = 90
    minimum_history: int = 10
    large_multiple: int = 3
    high_value_minor: int = 50_000_00
    new_contact_days: int = 7
    frequency: tuple[tuple[int, int], ...] = ((5, 4), (30, 8), (60, 12), (1440, 24))
    surge_multiple: int = 3
    timing_offset_minutes: int = 330
    aml_days: int = 7
    aml_senders: int = 3
    aml_transfers: int = 4


RULES = Rules()


def risk_band(score: int, rules: Rules) -> str:
    return ("LOW", "MEDIUM", "HIGH", "CRITICAL")[sum(score >= cutoff for cutoff in rules.bands)]


def evaluate(payment: dict, history: list[dict], recent: dict[int, int], *,
             beneficiary_added_ms: int, known_beneficiary: bool, flagged: bool,
             recent_outgoing: int, rules: Rules = RULES) -> dict:
    amount, now = payment["amount_minor"], payment["created_ms"]
    baseline = [row for row in history if row["created_ms"] < now - clock.DAY]
    enough = len(baseline) >= rules.minimum_history
    amounts = sorted(row["amount_minor"] for row in baseline)
    average = round(mean(amounts)) if enough else None
    p90 = amounts[(len(amounts) - 1) * 9 // 10] if enough else None
    signals = []

    def signal(index, code, explanation, **evidence):
        signals.append({"code": code, "points": rules.weights[index], "explanation": explanation, "evidence": evidence})

    if enough and amount >= average * rules.large_multiple and amount > p90:
        signal(0, "unusually_large", "Amount exceeds the account's recent settled baseline.",
               amount_minor=amount, average_minor=average, p90_minor=p90)
    outgoing = payment["direction"] == "outgoing"
    new_contact = now - beneficiary_added_ms <= rules.new_contact_days * clock.DAY
    if outgoing and not known_beneficiary and new_contact and amount >= rules.high_value_minor:
        signal(1, "new_beneficiary_high_value", "A recently added beneficiary has no prior settlement from this account.",
               beneficiary_id=payment["beneficiary_id"], added_ms=beneficiary_added_ms, amount_minor=amount)
    breaches = [{"window_minutes": window, "count": recent[window], "threshold": limit}
                for window, limit in rules.frequency if recent.get(window, 0) >= limit]
    if breaches:
        signal(2, "unusual_frequency", "Submission frequency exceeds one or more configured limits.", windows=breaches)

    if enough:
        def period(ms):
            return ((ms // clock.MINUTE + rules.timing_offset_minutes) % 1440) // 240

        periods = Counter(period(row["created_ms"]) for row in baseline)
        current = period(now)
        if periods[current] / len(baseline) <= 0.05 and amount >= rules.high_value_minor:
            signal(3, "unusual_timing", "High-value transfer falls in a rarely used four-hour period.",
                   start_hour=current * 4, historical_count=periods[current], offset_minutes=rules.timing_offset_minutes)
        daily = sum(amounts) / max(1, rules.history_days - 1)
        if outgoing and recent_outgoing > 0 and recent_outgoing + amount >= max(rules.high_value_minor, daily * rules.surge_multiple):
            signal(4, "outgoing_surge", "Recent settled outgoing value plus this payment exceeds the historical daily baseline.",
                   total_minor=recent_outgoing + amount, average_daily_minor=round(daily), window_hours=24)
    if flagged:
        signal(5, "previously_flagged_entity", "A party has an active restriction or a prior high-priority fraud case.",
               account_id=payment["account_id"], counterparty_id=payment["counterparty_id"])

    score = min(100, max(0, sum(item["points"] for item in signals)))
    return {"score": score, "band": risk_band(score, rules), "alert": score >= rules.alert_score, "signals": signals,
            "baseline": {"settled_samples": len(baseline), "minimum_samples": rules.minimum_history,
                         "average_minor": average, "p90_minor": p90,
                         "example_payment_ids": [row["id"] for row in baseline[:5]]},
            "next_action": "Review the contributing signals and supporting transfers." if score >= rules.alert_score
                           else "Review alongside the gateway decision if additional evidence is requested."}


def assess(t: Tx, payment: dict, beneficiary: dict, restricted: list[dict]) -> None:
    p, rules = payment, RULES
    now = p["created_ms"]
    party = (p["account_id"], p["direction"])
    history = t.all(
        """SELECT s.payment_id AS id, s.created_ms, s.amount_minor FROM settlements s
           JOIN payments p ON p.id = s.payment_id
           WHERE s.account_id = ? AND p.direction = ? AND p.legacy_demo = 0 AND s.created_ms BETWEEN ? AND ?
           ORDER BY s.created_ms DESC, s.payment_id LIMIT 500""",
        (*party, now - rules.history_days * clock.DAY, now),
    )
    recent = {minutes: 1 + t.scalar(
        """SELECT COUNT(*) FROM payments WHERE account_id = ? AND direction = ? AND id <> ?
           AND legacy_demo = 0 AND created_ms BETWEEN ? AND ?""",
        (*party, p["id"], now - minutes * clock.MINUTE, now),
    ) for minutes, _ in rules.frequency}
    known = bool(t.scalar(
        """SELECT 1 FROM settlements s JOIN payments p ON p.id = s.payment_id
           WHERE s.account_id = ? AND p.direction = 'outgoing' AND s.counterparty_id = ? AND p.legacy_demo = 0
           AND s.created_ms <= ? LIMIT 1""", (p["account_id"], p["counterparty_id"], now),
    ))
    flagged = bool(restricted or t.scalar(
        """SELECT 1 FROM cases c JOIN payments p ON p.id = c.payment_id
           WHERE c.scope = ? AND p.id <> ? AND p.legacy_demo = 0 AND c.created_ms <= ?
           AND (p.counterparty_id = ? OR p.account_id = ?)
           AND (c.verdict IN ('fraud', 'confirmed_fraud') OR (c.hold_active = 1 AND c.state <> 'closed')) LIMIT 1""",
        (settings.analyst_scope, p["id"], now, p["counterparty_id"], p["account_id"]),
    ))
    recent_outgoing = t.scalar(
        """SELECT COALESCE(SUM(s.amount_minor), 0) FROM settlements s JOIN payments p ON p.id = s.payment_id
           WHERE s.account_id = ? AND p.direction = 'outgoing' AND p.legacy_demo = 0
           AND s.created_ms BETWEEN ? AND ?""", (p["account_id"], now - clock.DAY, now),
    ) if p["direction"] == "outgoing" else 0
    result = evaluate(p, history, recent, beneficiary_added_ms=beneficiary["created_ms"],
                      known_beneficiary=known, flagged=flagged, recent_outgoing=int(recent_outgoing))
    result["baseline"]["sample_limit"] = 500
    t.execute(
        """INSERT INTO transaction_risk(payment_id, assessed_ms, config_version, score, band, alert, findings)
           VALUES (?,?,?,?,?,?,?) ON CONFLICT (payment_id) DO NOTHING""",
        (p["id"], now, rules.version, result["score"], result["band"], int(result["alert"]), dumps(result)),
    )


def cluster(rows: list[dict], rules: Rules = RULES) -> dict | None:
    senders = {row["sender_key"] for row in rows}
    if len(senders) < rules.aml_senders or len(rows) < rules.aml_transfers:
        return None
    return {"sender_count": len(senders), "transaction_count": len(rows),
            "total_minor": sum(row["amount_minor"] for row in rows),
            "transactions": rows}


def recipient_key(t: Tx, payment: dict) -> str:
    if payment["direction"] == "incoming":
        return "acct:" + payment["account_id"]
    linked = t.scalar("SELECT sandbox_account_id FROM counterparties WHERE id = ?", (payment["counterparty_id"],))
    return "acct:" + linked if linked else "cp:" + payment["counterparty_id"]


def scan_recipient(t: Tx, key: str, now: int) -> None:
    rules = RULES
    start = now - rules.aml_days * clock.DAY
    scope = settings.analyst_scope
    previous = t.one(
        """SELECT window_end_ms FROM aml_alerts WHERE scope = ? AND pattern = ? AND recipient_key = ?
           AND window_end_ms >= ? ORDER BY window_end_ms DESC LIMIT 1""",
        (scope, PATTERN, key, start),
    )
    if previous:
        return
    kind, entity = key.split(":", 1)
    outgoing = "s.counterparty_id = ?" if kind == "cp" else (
        "s.counterparty_id IN (SELECT id FROM counterparties WHERE sandbox_account_id = ?)"
    )
    query = """
        SELECT s.payment_id, s.amount_minor, s.created_ms, 'acct:' || s.account_id AS sender_key
        FROM settlements s JOIN payments p ON p.id = s.payment_id
        WHERE p.direction = 'outgoing' AND p.legacy_demo = 0 AND s.created_ms BETWEEN ? AND ? AND
    """ + outgoing
    args = [start, now, entity]
    if kind == "acct":
        query += """ UNION ALL
            SELECT s.payment_id, s.amount_minor, s.created_ms,
              COALESCE('acct:' || cp.sandbox_account_id, 'cp:' || s.counterparty_id) AS sender_key
            FROM settlements s JOIN payments p ON p.id = s.payment_id
            JOIN counterparties cp ON cp.id = s.counterparty_id
            WHERE p.direction = 'incoming' AND p.legacy_demo = 0
              AND s.created_ms BETWEEN ? AND ? AND s.account_id = ?"""
        args += [start, now, entity]
    rows = t.all("SELECT * FROM (" + query + ") AS activity ORDER BY created_ms DESC, payment_id LIMIT 500", args)
    evidence = cluster(rows)
    if evidence is None:
        return
    evidence["explanation"] = "Multiple senders repeatedly transferred to the same recipient within the monitoring window."
    evidence["bounded"] = len(rows) == 500
    alert_id = new_id("aml")
    t.execute("""INSERT INTO aml_alerts(id, pattern, recipient_key, scope, status, severity, detected_ms,
               window_start_ms, window_end_ms, updated_ms, config_version, evidence)
               VALUES (?,?,?,?,'NEW','MEDIUM',?,?,?,?,?,?)""",
              (alert_id, PATTERN, key, scope, now, start, now, now, rules.version, dumps(evidence)))
    for row in rows:
        t.execute("INSERT INTO aml_alert_payments(id, alert_id, payment_id) VALUES (?,?,?)",
                  (new_id("alp"), alert_id, row["payment_id"]))


def assessment_view(row: dict) -> dict:
    return {**{key: row[key] for key in ("payment_id", "assessed_ms", "config_version")},
            **loads(row["findings"], {})}
