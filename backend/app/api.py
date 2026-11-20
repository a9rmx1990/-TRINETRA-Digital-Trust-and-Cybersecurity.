"""HTTP and WebSocket routes (v2). Customer and analyst routes are authenticated separately."""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auth, clock, customer
from .auth import Analyst, Owner, require_analyst, require_owner
from .config import settings
from .inference import get_runtime
from .policy import POLICY_VERSION
from .soc import actions, mcp, views
from .util import ApiError, const_eq

router = APIRouter(prefix="/api/v2")


# ============================================================ customer
@router.post("/session", status_code=201)
def new_session():
    _, tok = auth.create_owner()
    return {"token": tok, "environment": "Banking sandbox"}


@router.get("/me")
def me(owner: Owner = Depends(require_owner)):
    return {"accounts": customer.list_accounts(owner.id), "beneficiaries": customer.list_beneficiaries(owner.id)}


class AccountIn(BaseModel):
    display_name: str = Field(max_length=80)


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, owner: Owner = Depends(require_owner)):
    return customer.create_account(owner.id, body.display_name)


@router.get("/accounts")
def list_accounts(owner: Owner = Depends(require_owner)):
    return {"items": customer.list_accounts(owner.id)}


class BeneficiaryIn(BaseModel):
    display_name: str = Field(max_length=80)
    account_ref: str = Field(max_length=40)


@router.post("/beneficiaries", status_code=201)
def add_beneficiary(body: BeneficiaryIn, owner: Owner = Depends(require_owner)):
    return customer.add_beneficiary(owner.id, body.display_name, body.account_ref)


@router.get("/beneficiaries")
def list_beneficiaries(owner: Owner = Depends(require_owner)):
    return {"items": customer.list_beneficiaries(owner.id)}


@router.delete("/beneficiaries/{bid}", status_code=204)
def remove_beneficiary(bid: str, owner: Owner = Depends(require_owner)):
    customer.remove_beneficiary(owner.id, bid)


class CallIn(BaseModel):
    consent: bool


@router.post("/calls", status_code=201)
def start_call(body: CallIn, owner: Owner = Depends(require_owner)):
    return customer.start_call(owner.id, body.consent)


@router.post("/calls/{cid}/offer")
def call_offer(cid: str, owner: Owner = Depends(require_owner)):
    raise ApiError(501, "webrtc_unavailable", "WebRTC negotiation is not enabled in this build. Stream PCM instead.")


@router.post("/calls/{cid}/pcm")
async def call_pcm(cid: str, request: Request, owner: Owner = Depends(require_owner)):
    data = await request.body()
    if len(data) > 256 * 1024:
        raise ApiError(413, "chunk_too_large", "Send audio in chunks of at most 256 KB.")
    return customer.append_pcm(owner.id, cid, data)


@router.get("/calls/{cid}")
def get_call(cid: str, owner: Owner = Depends(require_owner)):
    return customer.get_call(owner.id, cid)


@router.post("/calls/{cid}/finish")
async def finish_call(cid: str, owner: Owner = Depends(require_owner)):
    return await customer.finish_call(owner.id, cid)


@router.delete("/calls/{cid}", status_code=204)
def delete_call(cid: str, owner: Owner = Depends(require_owner)):
    customer.delete_call(owner.id, cid)


class PaymentIn(BaseModel):
    account_id: str
    beneficiary_id: str
    amount_minor: int
    channel: str
    remark: str | None = Field(default=None, max_length=140)
    call_id: str | None = None


@router.post("/payments")
async def submit_payment(body: PaymentIn, owner: Owner = Depends(require_owner),
                         idempotency_key: str | None = Header(default=None)):
    status, result = await customer.submit_payment(owner.id, idempotency_key, body.model_dump())
    return JSONResponse(result, status_code=status)


@router.post("/payment-requests")
async def submit_payment_request(body: PaymentIn, owner: Owner = Depends(require_owner),
                                 idempotency_key: str | None = Header(default=None)):
    status, result = await customer.submit_payment(owner.id, idempotency_key, body.model_dump(), direction="incoming")
    return JSONResponse(result, status_code=status)


@router.get("/payments")
def list_payments(owner: Owner = Depends(require_owner), limit: int = 50, before_ms: int | None = None):
    return customer.list_payments(owner.id, limit, before_ms)


@router.get("/payments/lookup")
def lookup_payment(key: str, owner: Owner = Depends(require_owner)):
    return customer.get_payment_by_key(owner.id, key)


@router.get("/payments/{pid}")
def get_payment(pid: str, owner: Owner = Depends(require_owner)):
    return JSONResponse(customer.get_payment(owner.id, pid), headers={"Cache-Control": "no-store"})


class VerifyIn(BaseModel):
    code: str = Field(max_length=12)


@router.post("/payments/{pid}/verify")
def verify(pid: str, body: VerifyIn, owner: Owner = Depends(require_owner)):
    return customer.verify_payment(owner.id, pid, body.code)


# ============================================================ analyst
soc = APIRouter(prefix="/api/v2/soc")


class LoginIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    passcode: str = Field(max_length=100)


@soc.post("/login")
def login(body: LoginIn):
    if not const_eq(body.passcode, auth.analyst_passcode()):
        raise ApiError(401, "invalid_credentials", "Name or passcode is incorrect.")
    return {"token": auth.issue_analyst_token(body.name.strip()), "scope": settings.analyst_scope}


@soc.get("/me")
def analyst_me(a: Analyst = Depends(require_analyst)):
    return {"name": a.name, "scope": a.scope, "tier": settings.soc_tier, "kill_switch": settings.soc_kill_switch}


@soc.get("/cases")
def list_cases(a: Analyst = Depends(require_analyst), from_ms: int | None = None, to_ms: int | None = None,
               state: str | None = None, severity: str | None = None, payment_state: str | None = None,
               sort: str = "priority", limit: int = 50, offset: int = 0):
    return views.queue(frm=from_ms, to=to_ms, state=state, severity=severity, payment_state=payment_state,
                       sort=sort, limit=limit, offset=max(0, offset))


@soc.get("/cases/{case_id}")
def get_case(case_id: str, a: Analyst = Depends(require_analyst)):
    return views.case_file(case_id)


class ActionIn(BaseModel):
    action: str
    expected_version: int
    rationale: str = Field(max_length=1000)
    params: dict = Field(default_factory=dict)
    command_key: str | None = Field(default=None, max_length=80)


@soc.post("/cases/{case_id}/actions")
def case_action(case_id: str, body: ActionIn, a: Analyst = Depends(require_analyst)):
    return actions.apply(actor=a.name, role="analyst", case_id=case_id, action=body.action,
                         expected_version=body.expected_version, rationale=body.rationale, params=body.params,
                         command_key=body.command_key)


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    expected_version: int
    rationale: str = Field(max_length=1000)
    command_key: str | None = Field(default=None, max_length=80)


@soc.post("/proposals/{proposal_id}/review")
def review(proposal_id: str, body: ReviewIn, a: Analyst = Depends(require_analyst)):
    return actions.review_proposal(actor=a.name, proposal_id=proposal_id, decision=body.decision,
                                   expected_version=body.expected_version, rationale=body.rationale,
                                   command_key=body.command_key)


@soc.get("/events")
def events(after: int = 0, limit: int = 200, a: Analyst = Depends(require_analyst)):
    return views.replay(after, limit)


@soc.get("/analytics")
def analytics(a: Analyst = Depends(require_analyst), from_ms: int | None = None, to_ms: int | None = None,
              tz_offset_min: int = Query(default=0, ge=-840, le=840)):
    return views.analytics(from_ms, to_ms, tz_offset_min)


@soc.get("/analytics/rows")
def analytics_rows(from_ms: int, to_ms: int, decision: str | None = None, a: Analyst = Depends(require_analyst)):
    return views.bucket_rows(from_ms, to_ms, decision)


@soc.get("/models")
def models(a: Analyst = Depends(require_analyst)):
    rt = get_runtime()
    return {"models": rt.manifest.describe(), "policy_version": POLICY_VERSION}


@soc.post("/mcp")
async def mcp_endpoint(request: Request, a: Analyst = Depends(require_analyst)):
    req = await request.json()
    return await asyncio.to_thread(mcp.jsonrpc, "analyst_read", req, actor=a.name)


@soc.websocket("/stream")
async def stream(ws: WebSocket):
    """First client message must be {"type":"auth","token":...,"after":cursor}. Server sends committed change
    notices ordered by delivery cursor; clients fetch authorized snapshots and advance their cursor."""
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        analyst = auth.verify_analyst_token(first.get("token"))
        after = int(first.get("after") or 0)
    except Exception:  # noqa: BLE001
        await ws.send_json({"type": "error", "code": "unauthenticated"})
        await ws.close(code=4401)
        return
    await ws.send_json({"type": "ready", "scope": analyst.scope, "after": after})
    try:
        while True:
            try:
                analyst = auth.verify_analyst_token(first.get("token"))
            except ApiError:
                await ws.send_json({"type": "error", "code": "expired"})
                await ws.close(code=4401)
                return
            batch = await asyncio.to_thread(views.replay, after, 200)
            for n in batch["notices"]:
                await ws.send_json({"type": "notice", **n})
                after = n["cursor"]
            if not batch["notices"]:
                await ws.send_json({"type": "heartbeat", "watermark": batch["watermark"]})
            await asyncio.sleep(0.4 if not batch["notices"] else 0.05)
    except (WebSocketDisconnect, RuntimeError):
        return


def health() -> dict:
    return {"ok": True, "time_ms": clock.now_ms(), "database": "postgres" if settings.database_url.startswith("postgres") else "sqlite"}
