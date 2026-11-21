"""Independent analyst workspace backed by the sandbox case ledger."""
from __future__ import annotations

import asyncio
import logging
import os
from importlib.util import find_spec
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import clock, policy
from ..config import settings
from ..db import dumps, get_db, loads
from ..soc import actions, mcp, views
from ..util import ApiError, const_eq, hmac_hex
from . import workflow

router = APIRouter(prefix="/api/v2/analyst")
log = logging.getLogger("trinetra.analyst")
run_slots = asyncio.Semaphore(2)


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


def analysis_facts(case: dict) -> dict:
    facts = workflow.case_facts(case)
    args = {"case_id": case["case"]["id"]}
    history = mcp.call_tool("triage", "case.history", args, actor="analyst-workspace")
    similar = mcp.call_tool("investigator", "cases.similar_closed", args, actor="analyst-workspace")
    facts["recent_payment_states"] = [row["state"] for row in history]
    facts["similar_case_verdicts"] = [row["verdict"] for row in similar]
    return facts


class Review(BaseModel):
    disposition: Literal["acknowledged", "follow_up"]
    note: str = Field(min_length=1, max_length=1200)


class VerificationApproval(BaseModel):
    expected_version: int = Field(ge=1)
    rationale: str = Field(min_length=8, max_length=1200)


class IncomingVerification(BaseModel):
    expected_version: int = Field(ge=1)
    analysis_run_id: UUID


def workspace_password() -> str:
    password = os.getenv("TRINETRA_ANALYST_WORKSPACE_PASSWORD")
    if not password:
        raise ApiError(503, "analyst_setup", "Set TRINETRA_ANALYST_WORKSPACE_PASSWORD on the backend to enable sign-in.")
    return password


def session_signature(expiry: str) -> str:
    return hmac_hex(settings.server_secret, f"analyst-workspace:{expiry}:{workspace_password()}")


def require_session(authorization: str = Header(default="")) -> None:
    scheme, _, token = authorization.partition(" ")
    expiry, _, signature = token.partition(".")
    if (scheme.lower() != "bearer" or not expiry.isascii() or not expiry.isdecimal()
            or len(expiry) > 16 or int(expiry) <= clock.now_ms()
            or not const_eq(signature, session_signature(expiry))):
        raise ApiError(401, "analyst_session", "Sign in to the analyst workspace.")


@router.post("/login")
def login(credentials: Credentials):
    if not const_eq(workspace_password(), credentials.password) or credentials.username != "admin":
        raise ApiError(401, "analyst_credentials", "Username or password is incorrect.")
    expiry = str(clock.now_ms() + 8 * clock.HOUR)
    return {"token": expiry + "." + session_signature(expiry)}


def missing_packages() -> bool:
    return any(find_spec(package) is None for package in ("langchain", "langgraph", "langsmith"))


@router.get("/status", dependencies=[Depends(require_session)])
def status():
    reason = ("Install backend/requirements-analyst.txt." if missing_packages()
              else "Set GOOGLE_API_KEY on the backend." if not workflow.api_key() else None)
    return {"model": workflow.model_name(), "unavailable_reason": reason, "tracing": workflow.trace_enabled()}


@router.get("/cases", dependencies=[Depends(require_session)])
def cases(state: Literal["needs_action", "open", "monitoring", "closed"] | None = None,
          severity: Literal["low", "medium", "high", "critical"] | None = None,
          days: Literal["7", "30", "365"] = "30", offset: int = Query(0, ge=0)):
    now = clock.now_ms()
    return views.queue(frm=now - int(days) * clock.DAY, to=now, state=state, severity=severity,
                       payment_state=None, sort="priority", limit=20, offset=offset)


def latest_run(case_id: str) -> dict | None:
    row = get_db().read(lambda t: t.one(
        "SELECT * FROM analyst_workspace_runs WHERE case_id = ? ORDER BY case_version DESC LIMIT 1", (case_id,)
    ))
    if row:
        row["findings"] = loads(row["findings"])
        row["metrics"] = loads(row.get("metrics"), {})
    return row


def claim_analysis_lease(case_id: str, run_id: str) -> bool:
    now = clock.now_ms()
    return get_db().write(lambda t: t.rowcount(
        """INSERT INTO analyst_analysis_leases(case_id, run_id, lease_until_ms) VALUES (?, ?, ?)
           ON CONFLICT (case_id) DO UPDATE SET run_id = excluded.run_id, lease_until_ms = excluded.lease_until_ms
           WHERE analyst_analysis_leases.lease_until_ms <= ?""",
        (case_id, run_id, now + 90_000, now),
    ) == 1)


def release_analysis_lease(case_id: str, run_id: str) -> None:
    get_db().write(lambda t: t.execute(
        "DELETE FROM analyst_analysis_leases WHERE case_id = ? AND run_id = ?", (case_id, run_id)))


def _workspace_evidence(item: dict) -> dict:
    result = {key: value for key, value in item.items() if key != "payload"}
    if item["kind"] == "voice_authenticity":
        prediction = item["payload"].get("prediction")
        score = item["score"]
        # Older diagnostic records from this checkpoint stored the score before the label was added.
        if (prediction is None and item["status"] == "inconclusive"
                and item["model_id"] == "SpeechAntiSpoofingBenchmarks/AASIST-L"
                and item["revision"] == "357e022c44a1aa926097e18c1457bde3873ed8bf"
                and item["payload"].get("reason") == "detector enabled for diagnostics only"
                and score is not None and 0 <= score <= 1):
            prediction = "fake" if score >= 0.5 else "real"
        result["prediction"] = prediction
    return result


def _investigator_evidence(items: list[dict]) -> dict:
    by_kind = {item["kind"]: item["payload"] for item in items}
    quality = by_kind.get("capture_quality", {})
    voice = by_kind.get("voice_authenticity", {})
    return {
        "graph": by_kind.get("recipient_graph_snapshot"),
        "capture": {key: quality[key] for key in (
            "duration_ms", "voiced_ms", "rms_dbfs", "clipped_ratio", "frame_ms", "levels_dbfs",
        ) if key in quality} if quality else None,
        "voice_windows": [
            {key: point[key] for key in ("offset_ms", "window_ms", "score")}
            for point in voice.get("points") or []
            if all(type(point.get(key)) in (int, float) for key in ("offset_ms", "window_ms", "score"))
        ],
    }


@router.get("/cases/{case_id}", dependencies=[Depends(require_session)])
def detail(case_id: str):
    case = views.case_file(case_id)
    challenge = case["payment"]["challenge"]
    watch = case["watch"]
    if watch:
        last_check = next((event for event in reversed(case["timeline"])
                           if event["type"] in ("watch_checked", "watch_alert")), None)
        watch = {**watch, "reopened_on_last_check": (
            last_check is not None and last_check["type"] == "watch_alert"
            and last_check["prev_state"] in ("closed", "monitoring")
            and last_check["new_state"] == "open"
        )}
    verified_run = next((e["data"]["params"]["analysis_run_id"] for e in reversed(case["timeline"])
                         if e["type"] == "action_verify_incoming"), None)
    eligible = {item["action"] for item in case["eligible_actions"]}
    return {
        **{key: case[key] for key in ("case", "customer", "sender", "beneficiary", "linked_transactions",
                                     "risk_assessment", "aml_alerts")},
        "watch": watch,
        "payment": {k: v for k, v in case["payment"].items() if k != "remark"},
        "suspicion_level": policy.suspicion_level(case["payment"]["decision"], case["payment"]["reasons"]),
        "evidence": [_workspace_evidence(item) for item in case["evidence"]],
        "investigator": _investigator_evidence(case["evidence"]),
        "timeline": [{k: e[k] for k in ("id", "type", "actor", "created_ms")} for e in case["timeline"][-40:]],
        "verification": {
            "available": bool({"issue_challenge", "verify_incoming"} & eligible),
            "verified_run_id": verified_run,
            "delivered_until_ms": challenge["expires_ms"]
            if challenge and challenge["receipt_delivery"] and challenge["status"] == "active" else None,
        },
        "run": latest_run(case_id),
    }


@router.post("/cases/{case_id}/verification-code", dependencies=[Depends(require_session)])
def approve_verification(case_id: str, body: VerificationApproval):
    return actions.apply(actor="admin", role="analyst", case_id=case_id, action="issue_challenge",
                         expected_version=body.expected_version, rationale=body.rationale, deliver_to_receipt=True)


@router.post("/cases/{case_id}/verify", dependencies=[Depends(require_session)])
def verify_incoming(case_id: str, body: IncomingVerification):
    return actions.apply(actor="admin", role="analyst", case_id=case_id, action="verify_incoming",
                         expected_version=body.expected_version, rationale="Verified after reviewing the Gemini findings.",
                         params={"analysis_run_id": str(body.analysis_run_id)}, via="analyst_workspace")


@router.post("/cases/{case_id}/analysis", dependencies=[Depends(require_session)])
async def run_analysis(case_id: str):
    case = await run_in_threadpool(views.case_file, case_id)
    version = case["case"]["version"]
    previous = await run_in_threadpool(latest_run, case_id)
    if previous and previous["case_version"] == version:
        return previous
    readiness = status()
    if readiness["unavailable_reason"]:
        raise ApiError(503, "analyst_model_setup", readiness["unavailable_reason"])
    if run_slots.locked():
        raise ApiError(429, "analyst_busy", "Two analyses are running. Try again shortly.")
    key = workflow.api_key()
    assert key is not None
    run_id = uuid4()
    run_key = str(run_id)
    claimed = await run_in_threadpool(claim_analysis_lease, case_id, run_key)
    if not claimed:
        raise ApiError(409, "analyst_running", "An analysis for this case is already running.")
    try:
        # Another process may have completed this case/version between our first read and lease claim.
        previous = await run_in_threadpool(latest_run, case_id)
        if previous and previous["case_version"] == version:
            return previous
        async with run_slots, asyncio.timeout(70):
            facts = await run_in_threadpool(analysis_facts, case)
            findings = await workflow.analyze(facts, run_id, readiness["model"], key)
            await run_in_threadpool(get_db().write, lambda t: t.execute(
                """INSERT INTO analyst_workspace_runs (id, case_id, case_version, model, findings, metrics, created_ms, traced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (case_id, case_version) DO NOTHING""",
                (run_key, case_id, version, readiness["model"], dumps(findings),
                 dumps(getattr(findings, "metrics", {})), clock.now_ms(), int(readiness["tracing"])),
            ))
    except TimeoutError:
        raise ApiError(504, "analyst_timeout", "The analysis timed out. Try again.") from None
    finally:
        try:
            await run_in_threadpool(release_analysis_lease, case_id, run_key)
        except Exception as exc:  # noqa: BLE001
            # The lease expires automatically if a transient DB fault prevents release.
            log.warning("analysis lease release failed: %s", type(exc).__name__)
    return await run_in_threadpool(latest_run, case_id)


@router.post("/cases/{case_id}/analysis/{run_id}/review", dependencies=[Depends(require_session)])
def review(case_id: str, run_id: str, body: Review):
    views.case_file(case_id)
    note = body.note.strip()
    if not note:
        raise ApiError(422, "review_note", "Enter a review note.")
    changed = get_db().write(lambda t: t.execute(
        """UPDATE analyst_workspace_runs SET disposition = ?, note = ?, reviewed_ms = ?
           WHERE id = ? AND case_id = ? AND disposition IS NULL
             AND case_version = (SELECT version FROM cases WHERE id = ? AND scope = ?)""",
        (body.disposition, note, clock.now_ms(), run_id, case_id, case_id, settings.analyst_scope),
    ).rowcount)
    if not changed:
        raise ApiError(409, "review_conflict", "This analysis changed or was already reviewed. Refresh the case.")
    return latest_run(case_id)
