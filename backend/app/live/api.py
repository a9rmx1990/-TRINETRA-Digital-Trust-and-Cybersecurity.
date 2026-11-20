"""Versioned sandbox caller and analyst API."""

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.simulator.scenarios import get_scenarios

from .ledger import RECIPIENTS, Ledger, open_ledger, payment_brief as brief
from .media import POOL, sessions
from .models import acoustic_baseline, models
from .soc_worker import apply_agent_action, run as run_soc, run_investigation


@asynccontextmanager
async def lifespan(app):
    app.state.sandbox = open_ledger()
    app.state.sandbox.jobs.backfill()
    await sessions.start()

    async def collect():
        while True:
            await asyncio.sleep(3)
            await sessions.expire()

    tasks = [asyncio.create_task(collect())]
    if os.getenv("TRINETRA_SOC_INLINE", "1") == "1":
        tasks.append(asyncio.create_task(run_soc(app.state.sandbox)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await sessions.shutdown()


router = APIRouter(prefix="/api/v2", lifespan=lifespan)
Authorization = Annotated[str, Header(max_length=512)]


def credential(value):
    return value.removeprefix("Bearer ") if value.startswith("Bearer ") else ""


def customer(authorization: Authorization):
    token = credential(authorization)
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise HTTPException(401, "Sandbox customer session required")
    return hashlib.sha256(token.encode()).hexdigest()


def is_analyst(value):
    expected = os.getenv("TRINETRA_ANALYST_KEY", "")
    return bool(expected) and secrets.compare_digest(value.encode(), expected.encode())


def analyst(authorization: Authorization):
    if not is_analyst(credential(authorization)):
        raise HTTPException(401, "Invalid sandbox analyst key")


def ledger(request: Request):
    return request.app.state.sandbox


Customer = Annotated[str, Depends(customer)]
Db = Annotated[Ledger, Depends(ledger)]
Analyst = Depends(analyst)


class Consent(BaseModel):
    consent: Literal[True]


class Offer(BaseModel):
    sdp: str = Field(min_length=1, max_length=32_768)


class Pay(BaseModel):
    recipient: str = Field(max_length=64)
    amount_minor: int = Field(strict=True, ge=1, le=100_000_000)
    channel: Literal["UPI", "IMPS", "WIRE"] = "UPI"
    narrative: str = Field(default="", max_length=1200)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Proof(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class CaseAction(BaseModel):
    action: Literal["RELEASE", "CONFIRM_FREEZE", "ISSUE_CHALLENGE"]
    version: int = Field(ge=1)
    note: str = Field(min_length=3, max_length=500, pattern=r"\S")


class ProposalReview(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=3, max_length=500, pattern=r"\S")


class VerdictOverride(BaseModel):
    version: int = Field(ge=1)
    verdict: Literal["fraud", "suspicious", "benign"]
    note: str = Field(min_length=3, max_length=500, pattern=r"\S")


class AgentControls(BaseModel):
    kill_switch: bool = Field(strict=True)


@router.get("/sandbox")
def sandbox():
    return {"recipients": list(RECIPIENTS), "configured_models": list(models.manifest),
            "analyst_enabled": bool(os.getenv("TRINETRA_ANALYST_KEY"))}


@router.post("/calls", status_code=201)
async def create_call(_: Consent, owner: Customer):
    result = await sessions.create(owner)
    servers = json.loads(os.getenv("TRINETRA_ICE_SERVERS", "[]"))
    return result | {"ice_servers": servers, "consent_version": "sandbox-v1"}


@router.post("/calls/{sid}/offer")
async def offer(sid: str, body: Offer, owner: Customer):
    return await sessions.offer(sid, sessions.get(sid, owner), body.sdp)


@router.post("/calls/{sid}/pcm", status_code=204)
async def pcm(sid: str, request: Request, owner: Customer):
    call = sessions.get(sid, owner)
    if call.state != "capturing" or call.transport not in (None, "pcm"):
        raise HTTPException(409, "Call is not accepting PCM")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 32_000:
            raise HTTPException(413, "PCM chunk exceeds one second")
        data.extend(chunk)
    if not data or len(data) % 2:
        raise HTTPException(422, "Expected 16-bit mono PCM")
    if call.state != "capturing" or call.transport not in (None, "pcm"):
        raise HTTPException(409, "Call is not accepting PCM")
    call.transport = "pcm"
    sessions.append(sid, call, np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768)


def call_status(call):
    public = call.public()
    if evidence := public.pop("evidence"):
        public["coverage_ms"] = evidence["latest"]["end_ms"]
        public["transport"] = evidence["transport"]
    return public


@router.get("/calls/{sid}")
async def status(sid: str, owner: Customer):
    return call_status(sessions.get(sid, owner))


@router.post("/calls/{sid}/finish")
async def finish(sid: str, owner: Customer):
    call = sessions.get(sid, owner)
    await sessions.finish(sid, call)
    return call_status(call)


@router.delete("/calls/{sid}", status_code=204)
async def abandon(sid: str, owner: Customer):
    call = sessions.get(sid, owner)
    sessions.calls.pop(sid)
    call.state = "closed"
    if call.pending and not call.pending.done():
        call.pending.cancel()
    await sessions.close(call)
    if sessions.redis:
        from redis.exceptions import RedisError
        with suppress(RedisError):
            await sessions.redis.delete(sessions.key(sid))


@router.post("/payments")
async def pay(body: Pay, owner: Customer, db: Db,
              idempotency_key: Annotated[str, Header(min_length=16, max_length=96)]):
    call = sessions.calls.get(body.session_id) if body.session_id else None
    if call and call.owner != owner:
        raise HTTPException(404, "Call session unavailable")
    evidence = await sessions.snapshot(body.session_id, call) if call and call.expires > time.time() else None
    loop = asyncio.get_running_loop()

    async def score(fn, *args):
        try:
            return await asyncio.wait_for(loop.run_in_executor(POOL, fn, *args), 10)
        except TimeoutError:
            return None

    text_signal, graph_result = await asyncio.gather(
        score(models.text_score, body.narrative),
        score(db.score_recipient, body.recipient),
    )
    return brief(await run_in_threadpool(
        db.submit, owner, idempotency_key, body.model_dump(), evidence,
        text_signal or {"status": "timeout"},
        graph_result=graph_result or ({"status": "timeout"}, None),
    ))


@router.get("/payments/{pid}")
def payment(pid: str, owner: Customer, db: Db):
    return brief(db.get(pid, owner))


@router.post("/payments/{pid}/verify")
def verify(pid: str, body: Proof, owner: Customer, db: Db):
    return brief(db.verify(pid, owner, body.code))


DEMO_IDS = {
    "clean": "SCENARIO_1_BASELINE",
    "spoof": "SCENARIO_2_VOICE_CLONE",
    "mule": "SCENARIO_3_MULE_RING",
    "coercion": "SCENARIO_4_DIGITAL_ARREST",
}


@router.post("/demo/{kind}")
def demo(kind: Literal["clean", "spoof", "mule", "coercion", "step-up"], owner: Customer, db: Db):
    if os.getenv("TRINETRA_ENABLE_FIXTURES") != "1":
        raise HTTPException(404, "Route unavailable")
    evidence = None
    if kind == "step-up":
        payment = Pay(recipient="ACC-2002", amount_minor=500_000, session_id=uuid4().hex)
    else:
        fixture = get_scenarios()[DEMO_IDS[kind]]["payload"]
        recipient = {"mule": "MULE-NODE-1", "coercion": "ACC-NEW-2003"}.get(kind, "ACC-2002")
        payment = Pay(recipient=recipient, amount_minor=int(fixture["amount"] * 100),
                      narrative=fixture["narrative_context"])
        if raw := fixture["audio_base64"]:
            pcm_data = models.audio.parse_audio(base64.b64decode(raw))
            window = {"evidence_id": uuid4().hex, "start_ms": 0, "end_ms": 2000,
                      "baseline": acoustic_baseline(pcm_data), "asr": {"status": "missing"},
                      "spoof": {"status": "missing"}, "coercion": {"status": "missing"}}
            evidence = {"latest": window, "acoustic": window, "coercion": window,
                        "transport": "fixture", "history": []}
    return brief(db.submit(owner, uuid4().hex, payment.model_dump(), evidence, {"status": "missing"}, kind))


@router.get("/cases", dependencies=[Analyst])
def cases(db: Db, after: int = 0, include_closed: bool = False):
    return db.cases(max(0, after), include_closed)


@router.get("/cases/{pid}", dependencies=[Analyst])
def case(pid: str, db: Db):
    return db.case(pid)


@router.post("/cases/{pid}/action", dependencies=[Analyst])
def action(pid: str, body: CaseAction, db: Db):
    result = db.action(pid, body.action, body.version, body.note)
    return {"state": result["state"], "challenge_code": result.get("challenge_code")}


@router.post("/cases/{pid}/agent/proposals/{proposal_id}", dependencies=[Analyst])
def review_proposal(pid: str, proposal_id: str, body: ProposalReview, db: Db):
    if len(proposal_id) > 96:
        raise HTTPException(404, "Proposal unavailable")
    return apply_agent_action(db, pid, proposal_id, review=body.model_dump())


@router.get("/cases/{pid}/agent/challenge", dependencies=[Analyst])
def agent_challenge(pid: str, db: Db):
    return {"challenge_code": db.actions.active_code(pid)}


@router.post("/cases/{pid}/agent/override", dependencies=[Analyst])
def override_verdict(pid: str, body: VerdictOverride, db: Db):
    return db.actions.override(pid, body.version, body.verdict, body.note)


@router.post("/soc/controls", dependencies=[Analyst])
def agent_controls(body: AgentControls, db: Db):
    return db.actions.set_kill_switch(body.kill_switch)


@router.get("/soc/analytics", dependencies=[Analyst])
def soc_analytics(db: Db):
    return db.monitor.analytics()


@router.get("/soc/evaluation", dependencies=[Analyst])
def soc_evaluation(db: Db):
    return {"examples": db.monitor.evaluation()}


@router.get("/cases/{pid}/evidence", dependencies=[Analyst])
def query_case(pid: str, intent: Literal["downstream", "cycle", "voice", "transcript"], db: Db):
    return evidence_for(db.case(pid), intent)


def evidence_for(case_data, intent):
    evidence = case_data["evidence"]
    graph = evidence["graph"]
    call = evidence["call"]
    match intent:
        case "downstream":
            ids = graph["path"]
        case "cycle":
            ids = graph["cycle"]
        case "voice":
            return {"evidence": call["history"] if call else []}
        case "transcript":
            return {"evidence": call["coercion"]["asr"] if call else None}
    edges = {edge["data"]["id"]: edge for edge in graph["edges"]}
    return {"evidence": [edges[key] for key in ids if key in edges]}


@router.post("/cases/{pid}/question", dependencies=[Analyst])
def question(pid: str, body: Question, db: Db):
    terms = {
        "cycle": r"\b(cycles?|loops?)\b",
        "transcript": r"\b(transcripts?|heard|said|language)\b",
        "voice": r"\b(voice|acoustic|spoof|audio)\b",
        "downstream": r"\b(accounts?|neighbors?|downstream|hops?|paths?|linked)\b",
    }
    intent = next((key for key, pattern in terms.items() if re.search(pattern, body.question, re.I)), None)
    if intent is None:
        raise HTTPException(422, "Ask about downstream accounts, cycles, voice scores, or the transcript")
    return {"intent": intent, **evidence_for(db.case(pid), intent)}


@router.post("/cases/{pid}/summary", dependencies=[Analyst])
async def summary(pid: str, db: Db):
    return await run_investigation(db, pid)


@router.websocket("/case-stream")
async def case_stream(ws: WebSocket):
    await ws.accept()
    try:
        auth = await asyncio.wait_for(ws.receive_json(), 5)
        if not isinstance(auth, dict) or not isinstance(auth.get("key"), str) or not is_analyst(auth["key"]):
            await ws.close(code=1008)
            return
        cursor = max(0, int(auth.get("after", 0)))
        db = ws.app.state.sandbox
        await ws.send_json({"cursor": cursor, "updated_ids": []})
        while True:
            updates = await run_in_threadpool(db.updates, cursor)
            if updates["cursor"] != cursor:
                cursor = updates["cursor"]
                await ws.send_json({"cursor": cursor, "updated_ids": updates["updated_ids"]})
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=2)
            except TimeoutError:
                continue
    except (WebSocketDisconnect, TimeoutError, ValueError, TypeError):
        return
