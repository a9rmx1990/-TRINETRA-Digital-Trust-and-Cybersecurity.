import hashlib
import json
import asyncio
from contextlib import suppress
import sqlite3

import httpx
import numpy as np

from app.main import app
from app.live.ledger import Ledger, decide, models, voice_verdict


CALLER = {"Authorization": "Bearer " + "a" * 64}
OTHER = {"Authorization": "Bearer " + "b" * 64}
ANALYST = {"Authorization": "Bearer test-analyst"}
KEY = {"Idempotency-Key": "test-key-for-payment-0001"}


def test_sandbox_payment_media_and_operator_invariants(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    monkeypatch.setenv("TRINETRA_DB", str(path))
    monkeypatch.setenv("TRINETRA_ANALYST_KEY", "test-analyst")
    monkeypatch.delenv("TRINETRA_ENABLE_FIXTURES", raising=False)
    monkeypatch.delenv("TRINETRA_LOCAL_LLM_PORT", raising=False)
    monkeypatch.setattr(models, "manifest", {})

    async def tick():
        # Keep the loop polling in restricted runners that block cross-thread wakeups.
        while True:
            await asyncio.sleep(0.012)

    async def flow():
        pulse = asyncio.create_task(tick())
        try:
            async with (app.router.lifespan_context(app),
                        httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                          base_url="http://test/api/v2") as client):
                assert (await client.get("cases", headers=CALLER)).status_code == 401
                call = await client.post("calls", headers=CALLER, json={"consent": True})
                assert call.status_code == 201
                sid = call.json()["session_id"]
                assert (await client.get(f"calls/{sid}", headers=OTHER)).status_code == 404
                t = np.arange(16000) / 16000
                pcm = (6000 * np.sin(2 * np.pi * 220 * t)).astype("<i2").tobytes()
                for _ in range(2):
                    assert (await client.post(f"calls/{sid}/pcm", content=pcm, headers=CALLER)).status_code == 204
                assert (await client.post(f"calls/{sid}/finish", headers=CALLER)).json()["state"] == "ready"
                body = {"recipient": "ACC-2002", "amount_minor": 100_000, "session_id": sid}
                first, retry = await asyncio.gather(*(
                    client.post("payments", headers=CALLER | KEY, json=body) for _ in range(2)
                ))
                assert first.status_code == retry.status_code == 200
                assert first.json() == retry.json()
                settled = first.json()["payment_id"]
                assert first.json()["state"] == "STEP_UP_REQUIRED"
                assert (await client.get(f"payments/{settled}", headers=OTHER)).status_code == 404
                conflict = await client.post("payments", headers=CALLER | KEY,
                                             json=body | {"amount_minor": 2000})
                assert conflict.status_code == 409
                assert Ledger(path).get(settled, hashlib.sha256(("a" * 64).encode()).hexdigest())[
                    "evidence"]["call"]["latest"]["end_ms"] == 2000

                voice_case = (await client.get(f"cases/{settled}", headers=ANALYST)).json()
                assert first.json()["amount_minor"] == voice_case["amount_minor"] == 100_000
                assert voice_case["payment_id"] == settled
                assert voice_case["voice_verdict"] == "inconclusive"
                assert "Verify the customer" in voice_case["triage"]["recommendation"]
                assert voice_case["triage"]["references"]["window"]
                assert (await client.post("demo/clean", headers=CALLER)).status_code == 404
                monkeypatch.setenv("TRINETRA_ENABLE_FIXTURES", "1")
                outcomes = {}
                for scenario in ("clean", "spoof", "mule", "coercion", "step-up"):
                    response = await client.post(f"demo/{scenario}", headers=CALLER)
                    assert response.status_code == 200, response.text
                    outcomes[scenario] = response.json()["payment_id"]
                    expected = "SETTLED" if scenario == "clean" else "STEP_UP_REQUIRED" if scenario == "step-up" else "HELD"
                    assert response.json()["state"] == expected
                with sqlite3.connect(path) as db:
                    ids = {row[0] for row in db.execute("SELECT id FROM settled WHERE id NOT LIKE 'fixture:%'")}
                    assert ids == {outcomes["clean"]}

                mule = outcomes["mule"]
                case = (await client.get(f"cases/{mule}", headers=ANALYST)).json()
                assert len(case["evidence"]["graph"]["path"]) == 5
                summary = (await client.post(f"cases/{mule}/summary", headers=ANALYST)).json()
                assert len(summary["references"]["path"]) == 5
                assert (await client.get(f"cases/{mule}/evidence?intent=downstream", headers=ANALYST)
                        ).json()["evidence"]
                question = await client.post(f"cases/{mule}/question", headers=ANALYST,
                                             json={"question": "What accounts are linked downstream?"})
                assert question.json()["intent"] == "downstream"
                spoof = outcomes["spoof"]
                released = await client.post(f"cases/{spoof}/action", headers=ANALYST,
                                             json={"action": "RELEASE", "version": 1, "note": "Reviewed fixture"})
                assert released.json()["state"] == "SETTLED"
                step = outcomes["step-up"]
                assert (await client.post(f"payments/{step}/verify", json={"code": "wrong"}, headers=CALLER)
                        ).status_code == 409
                challenge = await client.post(f"cases/{step}/action", headers=ANALYST,
                                              json={"action": "ISSUE_CHALLENGE", "version": 1, "note": "Check fixture"})
                code = challenge.json()["challenge_code"]
                assert (await client.post(f"payments/{step}/verify", headers=OTHER, json={"code": code})).status_code == 404
                assert (await client.post(f"payments/{step}/verify", headers=CALLER,
                                          json={"code": "wrong"})).status_code == 422
                verify = await client.post(f"payments/{step}/verify", headers=CALLER, json={"code": code})
                assert verify.json()["state"] == "SETTLED"
                assert (await client.post(f"payments/{step}/verify", headers=CALLER, json={"code": code})
                        ).status_code == 409
                freeze = await client.post(f"cases/{mule}/action", headers=ANALYST,
                                           json={"action": "CONFIRM_FREEZE", "version": 1, "note": "Confirmed fixture"})
                assert freeze.json()["state"] == "HELD"
                stale = await client.post(f"cases/{mule}/action", headers=ANALYST,
                                          json={"action": "RELEASE", "version": 1, "note": "Stale operator"})
                assert stale.status_code == 409
                page = (await client.get("cases", headers=ANALYST)).json()
                assert page["cursor"] > 0
                assert any(item["payment_id"] == outcomes["clean"] and item["state"] == "SETTLED" for item in page["recent"])
                assert not any("evidence" in item for item in page["cases"])
                assert next(item for item in page["recent"] if item["payment_id"] == settled)["has_case"]
                assert next(item for item in page["recent"] if item["payment_id"] == settled)["amount_minor"] == 100_000
                assert next(item for item in page["recent"] if item["payment_id"] == outcomes["spoof"])["amount_minor"] == 85_000_000

                def ready(score):
                    return {"status": "ready", "version": "test", "score": score}

                monkeypatch.setattr(models, "manifest", {
                    "spoof": {"reviewed_genuine_threshold": 20, "reviewed_hold_threshold": 80},
                    "graph": {},
                })
                monkeypatch.setattr(models, "spoof_score", lambda pcm: ready(5))
                monkeypatch.setattr(models, "transcript", lambda pcm: {
                    "status": "ready", "text": "Spoken evidence", "language": "en",
                })
                monkeypatch.setattr(models, "text_score", lambda text, language=None:
                                    ready(80 if text == "Typed evidence" else 6))
                monkeypatch.setattr(models, "graph_score", lambda features, edges: ready(7))
                session = (await client.post("calls", headers=CALLER, json={"consent": True})).json()["session_id"]
                for _ in range(2):
                    assert (await client.post(f"calls/{session}/pcm", content=pcm, headers=CALLER)).status_code == 204
                assert (await client.post(f"calls/{session}/finish", headers=CALLER)).json()["state"] == "ready"
                screening = await client.post("payments", headers=CALLER | {
                    "Idempotency-Key": "learned-flow-test-key-0001",
                }, json=body | {"session_id": session, "narrative": "Typed evidence"})
                assert screening.json()["state"] == "HELD"
                screened = (await client.get(f"cases/{screening.json()['payment_id']}", headers=ANALYST)).json()
                assert screened["voice_verdict"] == "likely_genuine"
                assert screened["evidence"]["call"]["coercion"]["coercion"]["score"] == 6
                assert screened["evidence"]["narrative_model"]["score"] == 80
                assert screened["evidence"]["gnn"]["score"] == 7
        finally:
            pulse.cancel()
            with suppress(asyncio.CancelledError):
                await pulse

    asyncio.run(asyncio.wait_for(flow(), timeout=15))


def test_voice_labels_require_reviewed_thresholds_and_usable_speech(monkeypatch):
    monkeypatch.setattr(models, "manifest", {"spoof": {
        "reviewed_genuine_threshold": 20, "reviewed_hold_threshold": 80,
    }})
    assert voice_verdict({"status": "ready", "score": 10}, 0.8) == "likely_genuine"
    assert voice_verdict({"status": "ready", "score": 90}, 0.8) == "suspected_synthetic"
    assert voice_verdict({"status": "ready", "score": 50}, 0.8) == "inconclusive"
    assert voice_verdict({"status": "ready", "score": 90}, 0.1) == "inconclusive"
    assert voice_verdict({"status": "unavailable"}, 0.8) == "inconclusive"


def test_live_gate_uses_learned_signals_and_requires_usable_evidence(monkeypatch):
    monkeypatch.setattr(models, "manifest", {"spoof": {
        "reviewed_genuine_threshold": 20, "reviewed_hold_threshold": 80,
    }})
    ready = lambda score: {"status": "ready", "score": score}
    graph = {"score": 100, "reasons": ["High rule score"]}
    acoustic = {"spoof": ready(10), "voiced_fraction": 0.8, "baseline": {"score": 100}}
    evidence = {"acoustic": acoustic, "coercion": {"coercion": ready(5)}, "latest": {"evidence_id": "x"}}
    request = {"recipient": "ACC-2002", "amount_minor": 1999, "channel": "UPI",
               "narrative": "A typed remark", "session_id": "voice"}
    assert decide(request, evidence, ready(5), graph, ready(10), False)["decision"] == "ALLOW"
    assert decide(request, evidence, ready(85), graph, ready(10), False)["decision"] == "HOLD"
    assert decide(request, evidence, ready(5), graph, ready(85), False)["decision"] == "HOLD"
    assert decide(request, evidence, ready(5), graph, {"status": "stale", "score": 0},
                  False)["decision"] == "STEP_UP"
    acoustic["spoof"] = ready(95)
    assert decide(request, evidence, ready(5), graph, ready(10), False)["decision"] == "HOLD"

    monkeypatch.setattr(models, "manifest", {})
    fusion_inputs = []
    def record_inputs(voice, text, graph):
        fusion_inputs.append(voice)
        return {"status": "missing"}
    monkeypatch.setattr(models, "fusion", record_inputs)
    result = decide(request, evidence, ready(5), graph, ready(10), False)
    assert result["decision"] == "STEP_UP" and result["voice_verdict"] == "inconclusive"
    assert result["evidence"]["call"]["acoustic"]["spoof"]["score"] == 95
    assert fusion_inputs == [None]
    assert decide(request, evidence, ready(85), graph, ready(10), False)["decision"] == "HOLD"


def test_soc_investigates_payments_and_links_history_automatically(tmp_path, monkeypatch):
    from app.live import triage

    path = tmp_path / "soc.sqlite3"
    monkeypatch.setenv("TRINETRA_DB", str(path))
    monkeypatch.setenv("TRINETRA_ANALYST_KEY", "test-analyst")
    monkeypatch.setenv("TRINETRA_LOCAL_LLM_PORT", "8080")
    monkeypatch.setenv("TRINETRA_COPILOT_AUTO", "1")
    monkeypatch.setattr(models, "manifest", {})
    real_client = httpx.AsyncClient
    requests = []

    def provider(request):
        assert request.url.host == "127.0.0.1" and "Authorization" not in request.headers
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"summary":"Prior cases share the recipient.","review_focus":"identity"}',
        }}]})

    monkeypatch.setattr(triage.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(provider), **kwargs))

    async def tick():
        while True:
            await asyncio.sleep(0.012)

    async def flow():
        pulse = asyncio.create_task(tick())
        try:
            async with (app.router.lifespan_context(app),
                        real_client(transport=httpx.ASGITransport(app=app),
                                    base_url="http://test/api/v2") as client):
                payments = []
                for index, owner in enumerate((CALLER, OTHER)):
                    response = await client.post("payments", json={"recipient": "ACC-2002", "amount_minor": 5000},
                                                 headers=owner | {"Idempotency-Key": f"soc-integration-key-{index}"})
                    assert response.status_code == 200
                    payments.append(response.json()["payment_id"])
                for _ in range(40):
                    overview = (await client.get("cases", headers=ANALYST)).json()["overview"]
                    if overview["investigated"] == 2:
                        break
                    await asyncio.sleep(0.08)
                assert overview["investigated"] == overview["sessions"] == overview["flagged"] == 2
                assert overview["ai_assessed"] == 1
                assert sum(row["flagged"] for row in overview["daily"]) == 2
                first, second = [(await client.get(f"cases/{pid}", headers=ANALYST)).json() for pid in payments]
                assert first["triage"]["provider_status"] == "http_429"
                assert second["triage"]["source"] == "copilot"
                history = second["triage"]["history"]
                assert history["session_payments"] == 0
                assert history["recipient_flagged"] == history["other_session_recipient_flagged"] == 1
                assert [row["payment_id"] for row in history["related_cases"]] == payments[:1]
                assert first["triage"]["history"]["recipient_payments"] == 0
                assert second["events"][-1]["kind"] == "SOC_INVESTIGATION_COMPLETED"
                assert second["state"] == "STEP_UP_REQUIRED"
                evidence = json.loads(requests[1]["messages"][-1]["content"])
                assert evidence["prior_activity"]["recipient_flagged"] == 1
                assert evidence["transcript_excerpt"] is None
        finally:
            pulse.cancel()
            with suppress(asyncio.CancelledError):
                await pulse

    asyncio.run(asyncio.wait_for(flow(), timeout=8))
