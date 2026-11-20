import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.analyst import workflow
from app.util import ApiError


@pytest.fixture
def gemini_transport(monkeypatch):
    pytest.importorskip("langchain")
    pytest.importorskip("langgraph")
    pytest.importorskip("langsmith")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    client = httpx.AsyncClient

    def install(handler):
        def make_client(**kwargs):
            return client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(workflow.httpx, "AsyncClient", make_client)

    return install


def test_workflow_retries_only_the_interrupted_stages(gemini_transport):
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        context = json.loads(payload["contents"][0]["parts"][0]["text"])
        completed = list(context["prior_findings"])
        stage = list(workflow.ROLES)[len(completed)]
        first_attempt = stage not in calls
        calls.append(stage)
        if stage == "investigator" and first_attempt:
            raise httpx.ReadTimeout("Simulated read timeout", request=request)
        if stage == "monitor" and first_attempt:
            return httpx.Response(503)
        finding = {"summary": stage, "confidence": "low", "evidence_refs": [], "next_step": "Review the case."}
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(finding)}]}}],
        })

    gemini_transport(respond)
    result = asyncio.run(workflow.analyze({"evidence": []}, uuid4(), workflow.model_name(), "test-key"))

    assert list(result) == list(workflow.ROLES)
    assert calls == ["triage", "investigator", "investigator", "decision", "monitor", "monitor", "reporter"]


@pytest.mark.parametrize(("status", "attempts"), [(400, 1), (429, 1), (503, 2)])
def test_workflow_limits_retries_when_gemini_keeps_failing(gemini_transport, status, attempts):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status)

    gemini_transport(respond)
    with pytest.raises(ApiError) as error:
        asyncio.run(workflow.analyze({"evidence": []}, uuid4(), workflow.model_name(), "test-key"))

    assert error.value.detail["code"] == "gemini_api"
    assert len(calls) == attempts
