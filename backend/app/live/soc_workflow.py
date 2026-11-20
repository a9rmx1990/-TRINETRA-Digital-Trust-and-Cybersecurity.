"""Post-payment SOC workflow with bounded, case-scoped MCP access."""

import os
from typing import Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .soc_mcp import McpClient, McpSession
from .triage import investigate


Action = Literal["none", "step_up", "hold", "watchlist", "block_beneficiary", "freeze", "report"]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str
    verdict: Literal["fraud", "suspicious", "benign"]
    confidence: float = Field(ge=0, le=1)
    recommended_action: Action
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    rationale: str = Field(min_length=1, max_length=1000)


def resolve_verdict(raw, case, evidence_ids):
    allowed = set(evidence_ids)
    try:
        verdict = Verdict.model_validate(raw)
    except ValidationError:
        verdict = None
    if (verdict and verdict.case_id == case["payment_id"]
            and set(verdict.evidence_ids) <= allowed
            and len(set(verdict.evidence_ids)) == len(verdict.evidence_ids)
            and (verdict.verdict != "benign" or verdict.recommended_action == "none")):
        return verdict.model_dump()
    return Verdict(
        case_id=case["payment_id"], verdict="suspicious", confidence=0.0,
        recommended_action="none", evidence_ids=[f"case:{case['payment_id']}"],
        rationale="The deterministic payment policy flagged this case for analyst review.",
    ).model_dump()


class State(TypedDict, total=False):
    case: dict
    history: dict
    assessment: dict
    evidence_ids: list[str]
    features: list[float]


class Workflow:
    def __init__(self, ledger, snapshot, *, job=None):
        self.ledger = ledger
        self.snapshot = snapshot
        self.job = job
        self.run_id = job["id"] if job else f"refresh:{uuid4().hex}"

    def client(self, role, context=None):
        return McpClient(McpSession(self.ledger, self.snapshot, role, self.run_id, context=context))

    async def triage(self, state):
        client = self.client("triage")
        case = await run_in_threadpool(client.read, "get_case")
        history = await run_in_threadpool(client.read, "get_history")
        return {"case": case, "history": history}

    async def investigator(self, state):
        client = self.client("investigator")
        call = (await run_in_threadpool(client.read, "get_call"))["snapshot"]
        graph = await run_in_threadpool(client.read, "expand_graph")
        scores = {}
        for signal in ("voice", "coercion", "remarks", "gnn", "fusion"):
            scores[signal] = await run_in_threadpool(client.read, "explain_score", signal=signal)
        case = state["case"]
        evidence_ids = case["evidence_ids"] + [score["evidence_id"] for score in scores.values()]
        evidence_ids += [edge["data"]["id"] for edge in graph["edges"]]
        evidence_ids += [row["payment_id"] for row in state["history"]["related_cases"]]
        evidence_ids += [row["event_id"] for row in case["watch_signals"]]
        if call:
            evidence_ids += [call["acoustic"]["evidence_id"], call["coercion"]["evidence_id"]]
        payment = case | {"evidence": {"call": call, "graph": graph}}
        allow_provider = self.job is None or os.getenv("TRINETRA_COPILOT_AUTO", "1") == "1"
        memory = await run_in_threadpool(client.read, "get_similar_cases")
        history = state["history"] | {"similar_closed_cases": memory["cases"], "watch_signals": case["watch_signals"]}
        evidence_ids += [row["case_id"] for row in memory["cases"]]
        assessment = await investigate(payment, history, allow_provider=allow_provider,
                                       tools=client, scores=scores, evidence_ids=list(dict.fromkeys(evidence_ids)))
        assessment["severity"] = "high" if case["decision"] in {"HOLD", "BLOCK"} else "review"
        return {"assessment": assessment, "evidence_ids": evidence_ids, "features": memory["features"]}

    async def decision(self, state):
        assessment = state["assessment"].copy()
        proposal = assessment.pop("proposed_verdict", None)
        assessment["verdict"] = resolve_verdict(proposal, state["case"], state["evidence_ids"])
        return {"assessment": assessment}

    async def monitor(self, state):
        if self.job:
            await run_in_threadpool(self.client("monitor").read, "schedule_watch")
        return {}

    async def reporter(self, state):
        assessment = state["assessment"]
        reporter = self.client("reporter", assessment)
        alert = await run_in_threadpool(reporter.read, "draft_analyst_alert")
        metrics = await run_in_threadpool(reporter.read, "publish_metrics")
        return {"assessment": assessment | {"run_id": self.run_id, "features": state["features"],
                                             "report": {"alert": alert, "metrics": metrics}}}

    async def run(self):
        steps = (self.triage, self.investigator, self.decision, self.monitor, self.reporter)
        if os.getenv("TRINETRA_AGENT_ENGINE", "local") == "langgraph":
            from langgraph.graph import END, START, StateGraph

            graph = StateGraph(State)
            previous = START
            for step in steps:
                graph.add_node(step.__name__, step)
                graph.add_edge(previous, step.__name__)
                previous = step.__name__
            graph.add_edge(previous, END)
            state = await graph.compile().ainvoke({})
        else:
            state = {}
            for step in steps:
                state.update(await step(state))
        return state["assessment"]
