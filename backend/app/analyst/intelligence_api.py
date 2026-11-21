"""Analyst-only reads and audited AML dispositions."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from .. import clock, intelligence
from ..config import settings
from ..db import Tx, get_db, loads
from ..util import ApiError, new_id
from .api import require_session, router

Band = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AMLStatus = Literal["NEW", "UNDER_REVIEW", "ESCALATED", "RESOLVED", "FALSE_POSITIVE"]
RISK_JOIN = """FROM transaction_risk r JOIN payments p ON p.id = r.payment_id
               JOIN beneficiaries b ON b.id = p.beneficiary_id WHERE p.legacy_demo = 0"""
RISK_COLUMNS = """r.*, p.amount_minor, p.direction, p.state, p.account_id,
                  b.display_name AS beneficiary, p.created_ms, p.currency"""
secured = [Depends(require_session)]


def risk_row(row: dict) -> dict:
    return intelligence.assessment_view(row) | {k: row[k] for k in (
        "amount_minor", "direction", "state", "account_id", "beneficiary", "created_ms", "currency"
    )}


@router.get("/intelligence/config", dependencies=secured)
def config():
    return asdict(intelligence.RULES)


@router.get("/intelligence/risk", dependencies=secured)
def risk_list(band: Band | None = None, account_id: str | None = Query(None, max_length=80),
              from_ms: int | None = Query(None, ge=0), to_ms: int | None = Query(None, ge=0),
              beneficiary: str | None = Query(None, max_length=80),
              min_amount_minor: int | None = Query(None, ge=0, le=10_000_000_000),
              alerts_only: bool = False, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
    if from_ms is not None and to_ms is not None and from_ms > to_ms:
        raise ApiError(422, "invalid_date_range", "The start date must be before the end date.")
    sql = RISK_JOIN
    params = []
    for column, operator, value in (("r.band", "=", band), ("p.account_id", "=", account_id),
                                    ("p.created_ms", ">=", from_ms), ("p.created_ms", "<=", to_ms),
                                    ("p.amount_minor", ">=", min_amount_minor),
                                    ("r.alert", "=", 1 if alerts_only else None)):
        if value is not None:
            sql += f" AND {column} {operator} ?"
            params.append(value)
    if beneficiary:
        sql += " AND LOWER(b.display_name) LIKE ? ESCAPE '!'"
        params.append("%" + beneficiary.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%")

    def read(t: Tx):
        summary = t.one("""SELECT COUNT(*) AS total, SUM(CASE WHEN r.band = 'HIGH' THEN 1 ELSE 0 END) AS high,
            SUM(CASE WHEN r.band = 'CRITICAL' THEN 1 ELSE 0 END) AS critical,
            SUM(CASE WHEN r.band = 'MEDIUM' THEN 1 ELSE 0 END) AS medium,
            SUM(CASE WHEN r.alert = 1 THEN p.amount_minor ELSE 0 END) AS flagged_minor """ + sql, params)
        rows = t.all("SELECT " + RISK_COLUMNS + " " + sql +
                     " ORDER BY r.assessed_ms DESC, p.id LIMIT ? OFFSET ?", (*params, limit, offset))
        return {"items": [risk_row(row) for row in rows], "summary": {k: int(v or 0) for k, v in summary.items()}}

    return get_db().read(read)


@router.get("/intelligence/risk/{payment_id}", dependencies=secured)
def risk_detail(payment_id: str):
    row = get_db().read(lambda t: t.one("SELECT " + RISK_COLUMNS + " " + RISK_JOIN + " AND p.id = ?", (payment_id,)))
    if not row:
        raise ApiError(404, "risk_not_found", "No assessment was recorded for this payment.")
    return risk_row(row)


def aml_row(row: dict) -> dict:
    return {**{k: v for k, v in row.items() if k not in ("evidence", "scope")}, "evidence": loads(row["evidence"], {})}


@router.get("/intelligence/aml", dependencies=secured)
def aml_list(status: AMLStatus | None = None, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
    where = "WHERE scope = ?"
    params = [settings.analyst_scope]
    if status:
        where += " AND status = ?"
        params.append(status)

    def read(t: Tx):
        total = t.scalar(f"SELECT COUNT(*) FROM aml_alerts {where}", params)
        rows = t.all(f"SELECT * FROM aml_alerts {where} ORDER BY detected_ms DESC, id LIMIT ? OFFSET ?",
                     (*params, limit, offset))
        return {"items": [aml_row(row) for row in rows], "total": total}

    return get_db().read(read)


def get_alert(t: Tx, alert_id: str) -> dict:
    row = t.one("SELECT * FROM aml_alerts WHERE id = ? AND scope = ?", (alert_id, settings.analyst_scope))
    if not row:
        raise ApiError(404, "aml_not_found", "AML alert not found.")
    return row


@router.get("/intelligence/aml/{alert_id}", dependencies=secured)
def aml_detail(alert_id: str):
    def read(t: Tx):
        alert = aml_row(get_alert(t, alert_id))
        alert["reviews"] = t.all(
            """SELECT actor, prev_status, new_status, note, created_ms FROM aml_reviews
               WHERE alert_id = ? ORDER BY created_ms DESC, id DESC LIMIT 50""", (alert_id,))
        return alert

    return get_db().read(read)


class Disposition(BaseModel):
    status: Literal["UNDER_REVIEW", "ESCALATED", "RESOLVED", "FALSE_POSITIVE"]
    expected_status: AMLStatus
    note: str = Field(min_length=1, max_length=1200)


@router.post("/intelligence/aml/{alert_id}/review", dependencies=secured)
def review_aml(alert_id: str, body: Disposition):
    note = body.note.strip()
    if not note:
        raise ApiError(422, "review_note", "Enter a review note.")

    def update(t: Tx):
        t.lock_rows("aml_alerts", [alert_id])
        alert = get_alert(t, alert_id)
        if alert["status"] != body.expected_status or alert["status"] == body.status:
            raise ApiError(409, "aml_review_conflict", "The alert status changed. Refresh before reviewing.")
        now = clock.now_ms()
        t.execute("UPDATE aml_alerts SET status = ?, updated_ms = ? WHERE id = ?", (body.status, now, alert_id))
        t.execute("""INSERT INTO aml_reviews(id, alert_id, actor, prev_status, new_status, note, created_ms)
                     VALUES (?,?,?,?,?,?,?)""",
                  (new_id("amr"), alert_id, "admin", alert["status"], body.status, note, now))
        return {"status": body.status}

    return get_db().write(update)
