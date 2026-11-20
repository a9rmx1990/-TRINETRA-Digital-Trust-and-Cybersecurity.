import asyncio
from importlib.util import find_spec
import json
import os
import sqlite3
import time
from contextlib import suppress
from uuid import uuid4

import httpx
import pytest

from app.live import soc_actions, triage
from app.live.ledger import Ledger, models
from app.live.soc_monitor import DAY
from app.live.soc_store import LEASE_SECONDS
from app.live.soc_stream import Streams
from app.live.soc_worker import consume
from app.main import app


CALLER = {"Authorization": "Bearer " + "a" * 64}
ANALYST = {"Authorization": "Bearer demo-analyst"}
BODY = {"recipient": "ACC-2002", "amount_minor": 20_000, "channel": "UPI"}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    path = tmp_path / "sandbox.sqlite3"
    monkeypatch.setenv("TRINETRA_DB", str(path))
    monkeypatch.setenv("TRINETRA_ANALYST_KEY", "demo-analyst")
    monkeypatch.setenv("TRINETRA_SOC_INLINE", "0")
    monkeypatch.setenv("TRINETRA_ENABLE_FIXTURES", "1")
    monkeypatch.setenv("TRINETRA_AGENT_MAX_TIER", "0")
    monkeypatch.delenv("TRINETRA_DATABASE_URL", raising=False)
    monkeypatch.delenv("TRINETRA_SOC_REDIS_URL", raising=False)
    monkeypatch.delenv("TRINETRA_REDIS_URL", raising=False)
    monkeypatch.delenv("TRINETRA_LOCAL_LLM_PORT", raising=False)
    monkeypatch.delenv("TRINETRA_AGENT_ENGINE", raising=False)
    monkeypatch.setattr(models, "manifest", {})
    return path


def exercise(flow):
    async def run():
        async def tick():
            while True:
                await asyncio.sleep(0.012)

        pulse = asyncio.create_task(tick())
        try:
            await flow()
        finally:
            pulse.cancel()
            with suppress(asyncio.CancelledError):
                await pulse

    asyncio.run(asyncio.wait_for(run(), timeout=20))


async def payment(client, key):
    result = await client.post("/payments", json=BODY, headers=CALLER | {"Idempotency-Key": key})
    result.raise_for_status()
    return result.json()["payment_id"]


async def case(client, pid):
    result = await client.get(f"/cases/{pid}", headers=ANALYST)
    result.raise_for_status()
    return result.json()


def mock_provider(monkeypatch, propose):
    real_client = httpx.AsyncClient
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if payload["messages"][-1]["role"] != "tool":
            names = {tool["function"]["name"] for tool in payload["tools"]}
            assert "apply_action" not in names
            assert "expand_graph" in names
            return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
                {"id": "probe", "type": "function", "function": {"name": "apply_action", "arguments": "{}"}},
                {"id": "history", "type": "function", "function": {"name": "get_history", "arguments": "{}"}},
            ]}}]})
        assert json.loads(payload["messages"][-2]["content"])["error"] == "Tool unavailable for this role"
        evidence = json.loads(payload["messages"][1]["content"])
        pid = evidence["case_id"]
        proposed = propose(evidence)
        action, label = proposed if isinstance(proposed, tuple) else (proposed, "suspicious")
        content = {"summary": "Review the cited case record.", "review_focus": "identity",
                   "proposed_verdict": {"case_id": pid, "verdict": label, "confidence": 0.99,
                                        "recommended_action": action,
                                        "evidence_ids": [f"case:{pid}"], "rationale": "A cited case needs review."}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    monkeypatch.setenv("TRINETRA_LOCAL_LLM_PORT", "8080")
    monkeypatch.setenv("TRINETRA_COPILOT_AUTO", "1")
    monkeypatch.setattr(triage.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    return real_client, seen


def test_transactional_outbox_rolls_back_and_expired_lease_is_reclaimable(sandbox, monkeypatch):
    ledger = Ledger(sandbox)
    real_event = ledger.event

    def event(*args):
        real_event(*args)
        raise RuntimeError("Lost connection at commit boundary")

    monkeypatch.setattr(ledger, "event", event)
    with pytest.raises(RuntimeError, match="commit boundary"):
        ledger.submit("owner", "rollback", BODY, None, {"status": "missing"})
    with ledger.tx() as db:
        assert db.execute("SELECT id FROM soc_jobs").fetchall() == []
        assert db.execute("SELECT id FROM payments").fetchall() == []

    monkeypatch.setattr(ledger, "event", real_event)
    first = ledger.submit("owner", "repeat", BODY, None, {"status": "missing"})
    assert ledger.submit("owner", "repeat", BODY, None, {"status": "missing"}) == first
    now = time.time()
    leased = ledger.jobs.claim(now)
    assert leased["case_id"] == first["payment_id"]
    replacement = Ledger(sandbox).jobs
    assert replacement.claim(now + 1) is None
    reclaimed = replacement.claim(now + LEASE_SECONDS + 1)
    assert reclaimed["id"] == leased["id"] and reclaimed["lease"] != leased["lease"]
    assert not ledger.jobs.complete(leased)
    replacement.fail(reclaimed, now + LEASE_SECONDS + 1, "TemporaryFailure")
    assert replacement.claim(now + LEASE_SECONDS + 2) is None
    recovered = replacement.claim(now + LEASE_SECONDS + 6)
    assert replacement.complete(recovered)
    assert replacement.claim(now + LEASE_SECONDS + 100) is None


def test_agent_mcp_investigation_and_one_automatic_step_up(sandbox, monkeypatch):
    real_client, seen = mock_provider(monkeypatch, lambda _: "step_up")
    monkeypatch.setenv("TRINETRA_AGENT_MAX_TIER", "1")
    monkeypatch.setattr(soc_actions, "AUTO_ACTION_CAP", 1)

    async def flow():
        async with (app.router.lifespan_context(app), real_client(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v2") as client):
            first = await payment(client, "first-agent-action-key")
            second = await payment(client, "second-agent-action-key")
            ledger = app.state.sandbox
            # The run and the associated queued action are durable across worker restarts.
            assert await consume(ledger)
            first_case = await case(client, first)
            assert first_case["agent"]["proposals"][0]["status"] == "queued"
            assert first_case["triage"]["verdict"]["evidence_ids"] == [f"case:{first}"]
            assert first_case["agent"]["watch"]["status"] == "active"
            assert any(row["outcome"] == "denied" for row in first_case["agent"]["timeline"])
            assert await consume(Ledger(sandbox))
            assert await consume(Ledger(sandbox))
            assert not await consume(ledger)
            assert (await case(client, first))["agent"]["proposals"][0]["status"] == "applied"
            assert (await case(client, second))["agent"]["proposals"][0]["status"] == "pending"

            unauthorized = await client.get(f"/cases/{first}/agent/challenge", headers=CALLER)
            assert unauthorized.status_code == 401
            challenge = await client.get(f"/cases/{first}/agent/challenge", headers=ANALYST)
            code = challenge.json()["challenge_code"]
            verified = await client.post(f"/payments/{first}/verify", headers=CALLER, json={"code": code})
            assert verified.json()["state"] == "SETTLED"
            assert (await client.post(f"/payments/{first}/verify", headers=CALLER,
                                      json={"code": code})).status_code == 409
            assert "a" * 64 not in json.dumps(seen)
            assert code not in json.dumps(await case(client, first))
            assert (await client.get("/soc/analytics", headers=ANALYST)).json()["reports"] == 2
            with ledger.tx(write=True) as db:
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    db.execute("DELETE FROM soc_tool_audit WHERE case_id=?", (first,))

    exercise(flow)


def test_hold_approval_is_reversible_and_kill_switch_blocks_execution(sandbox, monkeypatch):
    real_client, _ = mock_provider(monkeypatch, lambda _: "hold")
    monkeypatch.setenv("TRINETRA_AGENT_MAX_TIER", "1")

    async def flow():
        async with (app.router.lifespan_context(app), real_client(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v2") as client):
            pid = await payment(client, "temporary-hold-case-key")
            ledger = app.state.sandbox
            assert await consume(ledger)
            selected = await case(client, pid)
            proposal = selected["agent"]["proposals"][0]
            assert proposal["status"] == "pending"
            path = f"/cases/{pid}/agent/proposals/{proposal['id']}"
            approved = {"decision": "approve", "note": "Time-limited review"}
            assert (await client.post(path, json=approved, headers=CALLER)).status_code == 401
            assert (await client.post("/soc/controls", json={"kill_switch": True}, headers=ANALYST)).is_success
            assert (await client.post(path, json=approved, headers=ANALYST)).status_code == 409
            assert (await client.post("/soc/controls", json={"kill_switch": False}, headers=ANALYST)).is_success
            assert (await client.post(path, json=approved, headers=ANALYST)).json()["status"] == "applied"
            assert (await client.post(path, json=approved, headers=ANALYST)).json()["status"] == "applied"
            selected = await case(client, pid)
            assert selected["agent"]["hold_until"] > time.time()
            response = await client.post(f"/cases/{pid}/action", headers=ANALYST,
                                         json={"action": "ISSUE_CHALLENGE", "note": "Verify sandbox",
                                               "version": selected["version"]})
            proof = response.json()["challenge_code"]
            denied = await client.post(f"/payments/{pid}/verify", headers=CALLER, json={"code": proof})
            assert denied.status_code == 409 and "Temporary SOC hold" in denied.json()["detail"]
            with ledger.tx(write=True) as db:
                db.execute("UPDATE soc_holds SET expires_at=? WHERE case_id=?", (time.time() - 1, pid))
            assert (await client.post(f"/payments/{pid}/verify", headers=CALLER,
                                      json={"code": proof})).json()["state"] == "SETTLED"

    exercise(flow)


def test_tier_two_approval_feedback_and_watch_reopen_only_the_case(sandbox, monkeypatch):
    real_client, _ = mock_provider(monkeypatch, lambda _: "freeze")
    monkeypatch.setenv("TRINETRA_AGENT_MAX_TIER", "2")

    async def flow():
        async with (app.router.lifespan_context(app), real_client(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v2") as client):
            async def spoof():
                response = await client.post("/demo/spoof", headers=CALLER)
                response.raise_for_status()
                assert response.json()["state"] == "HELD"
                return response.json()["payment_id"]

            first = await spoof()
            ledger = app.state.sandbox
            assert await consume(ledger)
            assert not await consume(ledger)
            item = await case(client, first)
            proposal = item["agent"]["proposals"][0]
            assert proposal["status"] == "pending"

            first_path = f"/cases/{first}/agent/proposals/{proposal['id']}"
            reject = {"decision": "reject", "note": "Analyst has independent evidence"}
            assert (await client.post(first_path, json=reject, headers=ANALYST)).json()["status"] == "rejected"
            release = {"action": "RELEASE", "version": item["version"], "note": "Release reviewed transfer"}
            assert (await client.post(f"/cases/{first}/action", json=release, headers=ANALYST)).json()["state"] == "SETTLED"
            item = await case(client, first)
            feedback = {"version": item["version"], "verdict": "benign", "note": "Adjudicated sandbox outcome"}
            assert (await client.post(f"/cases/{first}/agent/override", json=feedback, headers=ANALYST)).is_success
            assert (await client.get("/soc/evaluation", headers=ANALYST)).json()["examples"][0]["label"] == "benign"

            second = await spoof()
            restored = Ledger(sandbox)
            assert restored.monitor.tick(time.time() + DAY + 2)
            reopened = await case(client, first)
            assert reopened["case_status"] == "OPEN" and reopened["state"] == "SETTLED"
            assert any(event["kind"] == "SOC_WATCH_SIGNAL" for event in reopened["events"])
            while await consume(restored):
                pass
            item = await case(client, second)
            proposal = item["agent"]["proposals"][0]
            assert proposal["status"] == "pending"
            path = f"/cases/{second}/agent/proposals/{proposal['id']}"
            response = await client.post(path, headers=ANALYST, json={"decision": "approve", "note": "Freeze reviewed"})
            assert response.json()["status"] == "applied"
            assert (await case(client, second))["case_status"] == "CONFIRM_FREEZE"
            assert (await case(client, first))["state"] == "SETTLED"

    exercise(flow)


class MemoryStream:
    def __init__(self):
        self.published = []
        self.delivered = []
        self.acked = []

    def xgroup_create(self, *args, **kwargs):
        pass

    def xadd(self, stream, envelope, **kwargs):
        self.published.append((f"{len(self.published) + 1}-0", envelope))

    def xautoclaim(self, *args, **kwargs):
        return ("0-0", [])

    def xreadgroup(self, group, consumer, streams, **kwargs):
        if not self.published:
            return []
        entry = self.published.pop(0)
        self.delivered.append(entry)
        return [(next(iter(streams)), [entry])]

    def xack(self, stream, group, entry):
        self.acked.append(entry)


def test_stream_duplicates_acknowledge_one_durable_investigation(sandbox):
    async def flow():
        ledger = Ledger(sandbox)
        result = ledger.submit("owner", "stream-submit", BODY, None, {"status": "missing"})
        case_id = result["payment_id"]
        transport = MemoryStream()
        stream = Streams(transport)
        assert await consume(ledger, stream)
        assert ledger.case(case_id)["triage"]["provider_status"] == "not_configured"
        transport.published.append(("duplicate-0", transport.delivered[0][1]))
        assert not await consume(Ledger(sandbox), stream)
        assert transport.acked == ["1-0", "duplicate-0"]
        assert sum(row["kind"] == "SOC_INVESTIGATION_COMPLETED" for row in ledger.case(case_id)["events"]) == 1

    exercise(flow)


@pytest.mark.skipif(not os.getenv("TRINETRA_TEST_POSTGRES_URL"), reason="Requires an isolated Postgres service")
def test_postgres_migration_and_worker_replay_preserve_ledger(sandbox, monkeypatch):
    import psycopg
    from psycopg.conninfo import make_conninfo
    from tools.migrate_soc_postgres import migrate

    url = os.environ["TRINETRA_TEST_POSTGRES_URL"]
    schema = "test_soc_" + uuid4().hex
    destination = make_conninfo(url, options=f"-c search_path={schema}")
    sqlite = Ledger(sandbox)
    result = sqlite.submit("owner", "db-migration", BODY, None, {"status": "missing"})
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f"CREATE SCHEMA {schema}")
        try:
            assert migrate(sandbox, destination)["payments"] == 1
            ledger = Ledger(None, database_url=destination)
            assert ledger.get(result["payment_id"], "owner") == result

            async def flow():
                assert await consume(ledger)
                assert ledger.case(result["payment_id"])["triage"]["verdict"]["verdict"] == "suspicious"

            exercise(flow)
            with pytest.raises(ValueError, match="must be empty"):
                migrate(sandbox, destination)
        finally:
            connection.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.mark.skipif(not os.getenv("TRINETRA_TEST_REDIS_URL"), reason="Requires an isolated Redis service")
def test_redis_stream_delivery_and_acknowledgement(sandbox, monkeypatch):
    from redis import Redis
    from app.live import soc_stream

    key = "test:soc:" + uuid4().hex
    monkeypatch.setattr(soc_stream, "STREAM", key)
    broker = Redis.from_url(os.environ["TRINETRA_TEST_REDIS_URL"], decode_responses=True)
    ledger = Ledger(sandbox)
    ledger.submit("owner", "redis-stream", BODY, None, {"status": "missing"})

    async def flow():
        assert await consume(ledger, Streams(broker))
        assert broker.xpending(key, soc_stream.GROUP)["pending"] == 0

    try:
        exercise(flow)
    finally:
        broker.delete(key)
        broker.close()


def test_stdio_mcp_has_protocol_handshake_and_read_only_scope(sandbox):
    import subprocess
    import sys

    ledger = Ledger(sandbox)
    pid = ledger.submit("owner", "stdio-submit", BODY, None, {"status": "missing"})["payment_id"]
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_case", "arguments": {}}},
    ]
    result = subprocess.run(
        [sys.executable, "-m", "app.live.soc_mcp", pid, "--service", "case"],
        input="".join(json.dumps(message) + "\n" for message in messages),
        text=True, capture_output=True, check=True, timeout=5,
    )
    handshake, tools, call = [json.loads(line) for line in result.stdout.splitlines()]
    assert handshake["result"]["protocolVersion"] == "2025-11-25"
    assert [tool["name"] for tool in tools["result"]["tools"]] == ["get_case"]
    assert call["result"]["structuredContent"]["payment_id"] == pid
    assert "owner" not in call["result"]["structuredContent"]


def test_case_stream_replays_agent_timeline_after_reconnect(sandbox):
    from tools.test_support import test_client

    with test_client(app) as client:
        with client.websocket_connect("/api/v2/case-stream") as ws:
            ws.send_json({"key": "demo-analyst", "after": 0})
            assert ws.receive_json()["cursor"] == 0
            response = client.post("/api/v2/payments", headers=CALLER | {"Idempotency-Key": "ws-agent-case-key"},
                                   json=BODY)
            response.raise_for_status()
            pid = response.json()["payment_id"]
            notice = ws.receive_json()
            assert notice["updated_ids"] == [pid]

        async def run_worker():
            assert await consume(Ledger(sandbox))

        exercise(run_worker)
        with client.websocket_connect("/api/v2/case-stream") as ws:
            ws.send_json({"key": "demo-analyst", "after": notice["cursor"]})
            assert ws.receive_json()["cursor"] == notice["cursor"]
            update = ws.receive_json()
            assert update["cursor"] > notice["cursor"] and update["updated_ids"] == [pid]
        item = client.get(f"/api/v2/cases/{pid}", headers=ANALYST).json()
        assert any(step["tool"] == "get_call" for step in item["agent"]["timeline"])


def test_restricted_recipient_yields_block_and_an_auditable_case(sandbox):
    ledger = Ledger(sandbox)
    with ledger.tx(write=True) as db:
        db.execute("INSERT INTO restrictions VALUES (?)", (BODY["recipient"],))
    result = ledger.submit("owner", "restricted", BODY, None, {"status": "missing"})
    assert result["decision"] == "BLOCK" and result["state"] == "BLOCKED"
    assert ledger.jobs.claim(time.time())["case_id"] == result["payment_id"]
    with ledger.tx() as db:
        assert db.execute("SELECT id FROM settled").fetchall() == []


@pytest.mark.skipif(find_spec("langgraph") is None, reason="Requires optional LangGraph")
def test_langgraph_runs_the_same_scoped_state_machine(sandbox, monkeypatch):
    monkeypatch.setenv("TRINETRA_AGENT_ENGINE", "langgraph")

    async def flow():
        ledger = Ledger(sandbox)
        result = ledger.submit("owner", "langgraph-flow", BODY, None, {"status": "missing"})
        assert await consume(ledger)
        assert ledger.case(result["payment_id"])["triage"]["report"]["alert"]["case_id"] == result["payment_id"]

    exercise(flow)


@pytest.mark.parametrize("sampled", [False, True])
def test_benign_closure_applies_only_to_verified_case_and_samples_qa(sandbox, monkeypatch, sampled):
    real_client, _ = mock_provider(monkeypatch, lambda data: (
        "none", "benign" if data["payment_state"] == "SETTLED" else "suspicious"))
    monkeypatch.setenv("TRINETRA_AGENT_MAX_TIER", "1")
    monkeypatch.setenv("TRINETRA_AGENT_AUTO_CLOSE", "1")
    monkeypatch.setattr(soc_actions, "sample_closure", lambda case_id: sampled)

    async def flow():
        async with (app.router.lifespan_context(app), real_client(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v2") as client):
            pid = await payment(client, "benign-closure-key")
            ledger = app.state.sandbox
            assert await consume(ledger)
            assert (await case(client, pid))["agent"]["proposals"] == []
            issue = await client.post(f"/cases/{pid}/action", headers=ANALYST,
                                      json={"action": "ISSUE_CHALLENGE", "version": 1, "note": "Independent check"})
            proof = issue.json()["challenge_code"]
            verified = await client.post(f"/payments/{pid}/verify", headers=CALLER, json={"code": proof})
            assert verified.json()["state"] == "SETTLED"
            while await consume(ledger):
                pass
            item = await case(client, pid)
            proposal = item["agent"]["proposals"][0]
            assert proposal["action"] == "close_case"
            if sampled:
                assert item["case_status"] == "VERIFIED"
                assert proposal["status"] == "pending"
                reviewed = await client.post(f"/cases/{pid}/agent/proposals/{proposal['id']}", headers=ANALYST,
                                             json={"decision": "approve", "note": "Sampled closure review"})
                assert reviewed.json()["status"] == "applied"
            item = await case(client, pid)
            assert item["case_status"] == "CLOSED_BENIGN" and item["state"] == "SETTLED"

    exercise(flow)


@pytest.mark.skipif(find_spec("fastmcp") is None, reason="Requires optional FastMCP")
def test_fastmcp_adapter_exposes_the_same_case_scope(sandbox):
    from fastmcp import Client
    from app.live.soc_mcp import McpSession, fastmcp_server

    ledger = Ledger(sandbox)
    pid = ledger.submit("owner", "fastmcp-flow", BODY, None, {"status": "missing"})["payment_id"]
    server = fastmcp_server(McpSession(ledger, ledger.case(pid), "investigator", "sdk", service="case"))

    async def flow():
        async with Client(server) as client:
            assert [tool.name for tool in await client.list_tools()] == ["get_case"]
            reply = await client.call_tool("get_case", {})
            assert reply.structured_content["payment_id"] == pid

    exercise(flow)
