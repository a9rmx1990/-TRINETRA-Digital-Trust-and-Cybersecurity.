"""Case-scoped MCP tool service. The worker uses the same protocol as stdio clients."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


PROTOCOL_VERSION = "2025-11-25"
INSTRUCTION_TEXT = re.compile(
    r"\b(ignore|override|forget)\b.{0,60}\b(instructions?|rules?|polic(?:y|ies))\b|"
    r"\b(system|developer)\s+(prompt|message)\b|\bcall\s+(a\s+)?tool\b",
    re.IGNORECASE,
)


def transcript_excerpt(text):
    clean = " ".join("".join(char for char in text if char.isprintable() or char.isspace()).split())[:600]
    return "" if INSTRUCTION_TEXT.search(clean) else clean


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GraphArgs(ToolArgs):
    hops: int = Field(default=5, ge=1, le=5)


class ModelArgs(ToolArgs):
    signal: Literal["voice", "coercion", "remarks", "gnn", "fusion"]


class ProposalArgs(ToolArgs):
    proposal_id: str = Field(max_length=96)


@dataclass(frozen=True)
class Tool:
    service: str
    roles: frozenset[str]
    description: str
    args: type[ToolArgs]
    handler: str
    read_only: bool = True


TOOLS = {
    "get_case": Tool("case", frozenset({"triage", "investigator", "reporter", "monitor"}),
                     "Read the scoped case and its event references.", ToolArgs, "case"),
    "get_history": Tool("evidence", frozenset({"triage", "investigator", "monitor"}),
                        "Read bounded prior activity and linked cases.", ToolArgs, "history"),
    "get_call": Tool("evidence", frozenset({"investigator"}),
                     "Read the saved call evidence, model states and coverage.", ToolArgs, "call"),
    "expand_graph": Tool("graph", frozenset({"investigator"}),
                         "Inspect the saved recipient neighborhood up to five hops.", GraphArgs, "graph"),
    "explain_score": Tool("model", frozenset({"investigator"}),
                          "Read the versioned score and status for one detector.", ModelArgs, "score"),
    "get_similar_cases": Tool("evidence", frozenset({"investigator"}),
                              "Find closed cases with similar detector score profiles.", ToolArgs, "similar"),
    "apply_action": Tool("action", frozenset({"action"}),
                         "Apply a durable proposal through the autonomy gate.", ProposalArgs, "apply", False),
    "schedule_watch": Tool("scheduler", frozenset({"monitor"}),
                           "Schedule a durable follow-up for the scoped case.", ToolArgs, "watch", False),
    "draft_analyst_alert": Tool("notify", frozenset({"reporter"}),
                                "Prepare a local analyst alert from the validated verdict.", ToolArgs, "alert"),
    "publish_metrics": Tool("bi", frozenset({"reporter"}),
                            "Prepare structured insight for the analytics store.", ToolArgs, "metrics"),
}


def bounded_graph(graph, recipient, hops):
    edges = graph["edges"]
    expanded = {recipient}
    frontier = {recipient}
    kept = {}
    for _ in range(hops):
        adjacent = [edge for edge in edges if edge["data"]["source"] in frontier]
        frontier = {edge["data"]["target"] for edge in adjacent} - expanded
        expanded.update(frontier)
        for edge in adjacent:
            kept[edge["data"]["id"]] = edge
    return {key: graph[key] for key in ("score", "truncated", "watermark")} | {
        "edges": list(kept.values()),
        "path": [ref for ref in graph["path"] if ref in kept],
        "cycle": graph["cycle"] if set(graph["cycle"]) <= kept.keys() else [],
    }


class McpSession:
    def __init__(self, ledger, case, role, run_id, *, service=None, review=None, context=None):
        self.ledger = ledger
        self.data = case
        self.case_id = case["payment_id"]
        self.role = role
        self.run_id = run_id
        self.service = service
        self.review = review
        self.context = context or {}
        self.phase = "new"

    def tools(self):
        return {
            name: tool for name, tool in TOOLS.items()
            if self.role in tool.roles and (self.service is None or self.service == tool.service)
        }

    def case(self):
        keys = ("payment_id", "recipient", "amount_minor", "decision", "state", "version",
                "case_status", "policy_version", "voice_verdict", "risk_score", "reasons")
        events = [row for row in self.data["events"] if row["kind"] != "SOC_TOOL"][-15:]
        watch_signals = [signal for row in events if row["kind"] == "SOC_WATCH_SIGNAL"
                         for signal in row["detail"]["related"]]
        return {key: self.data[key] for key in keys} | {
            "evidence_ids": [f"case:{self.case_id}"] + [f"event:{row['seq']}" for row in events],
            "watch_signals": watch_signals[-5:],
        }

    def history(self):
        return self.ledger.investigation_history(self.case_id)

    def call(self):
        call = self.data["evidence"]["call"]
        if call is None:
            return {"status": "missing", "snapshot": None}
        asr = {key: value for key, value in call["coercion"]["asr"].items() if key not in {"segments", "text"}}
        if os.getenv("TRINETRA_COPILOT_TRANSCRIPT") == "1":
            asr["text"] = transcript_excerpt(call["coercion"]["asr"].get("text", ""))
        return {"status": "ready", "snapshot": call | {
            "coercion": call["coercion"] | {
                "asr": asr,
            },
            "latest": {"evidence_id": call["latest"]["evidence_id"], "end_ms": call["latest"]["end_ms"]},
            "acoustic": {key: value for key, value in call["acoustic"].items() if key != "asr"},
        }}

    def graph(self, hops):
        return bounded_graph(self.data["evidence"]["graph"], self.data["recipient"], hops)

    def score(self, signal):
        evidence = self.data["evidence"]
        call = evidence["call"]
        scores = {"gnn": evidence["gnn"], "fusion": evidence["fusion"], "remarks": evidence["narrative_model"]}
        if call:
            scores.update(voice=call["acoustic"]["spoof"], coercion=call["coercion"]["coercion"])
        return {"signal": signal, "evidence_id": f"score:{signal}:{self.case_id}"} | scores.get(
            signal, {"status": "missing"})

    def similar(self):
        features = [float(self.score(signal).get("score", 0)) / 100
                    for signal in ("voice", "coercion", "remarks", "gnn", "fusion")]
        return {"features": features, "cases": self.ledger.monitor.similar(self.case_id, features)}

    def apply(self, proposal_id):
        return self.ledger.actions.apply(self.case_id, proposal_id, review=self.review)

    def watch(self):
        with self.ledger.tx(write=True) as db:
            return self.ledger.monitor.schedule(db, self.case_id, time.time())

    def alert(self):
        verdict = self.context["verdict"]
        return {
            "channel": "analyst-dashboard", "case_id": self.case_id, "verdict": verdict["verdict"],
            "summary": self.context["summary"], "evidence_ids": verdict["evidence_ids"],
            "investigation_draft": {
                "state": "draft", "payment_state": self.data["state"], "amount_minor": self.data["amount_minor"],
                "recommendation": self.context["recommendation"], "rationale": verdict["rationale"],
            },
        }

    def metrics(self):
        verdict = self.context["verdict"]
        return {key: verdict[key] for key in ("verdict", "confidence", "recommended_action")}

    def audit(self, name, arguments, outcome, result=None):
        safe_result = None
        if result is not None:
            encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
            safe_result = {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}
            fields = ("status", "error", "score", "version", "evidence_id", "evidence_ids",
                      "path", "cycle", "related_cases", "cases", "verdict", "confidence")
            safe_result["evidence"] = {key: result[key] for key in fields if key in result}
        with self.ledger.tx(write=True) as db:
            db.execute(
                "INSERT INTO soc_tool_audit(case_id,run_id,role,tool,arguments,outcome,result,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (self.case_id, self.run_id, self.role, name,
                    json.dumps(arguments), outcome, json.dumps(safe_result), time.time()),
            )
            self.ledger.event(db, self.case_id, "SOC_TOOL", self.role,
                              {"run_id": self.run_id, "tool": name, "outcome": outcome})

    def receive(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self.error(None, -32600, "Invalid request")
        method, params, request_id = message.get("method"), message.get("params", {}), message.get("id")
        if "id" not in message:
            if method == "notifications/initialized" and self.phase == "initializing":
                self.phase = "ready"
            return None
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "Invalid parameters")
        if method == "initialize" and self.phase == "new":
            self.phase = "initializing"
            result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": f"trinetra-{self.service or 'soc'}", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif self.phase != "ready":
            return self.error(request_id, -32002, "Session is not initialized")
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": tool.description,
                                 "inputSchema": tool.args.model_json_schema(),
                                 "annotations": {"readOnlyHint": tool.read_only}}
                                for name, tool in self.tools().items()]}
        elif method == "tools/call":
            result = self.call_tool(params)
        else:
            return self.error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def call_tool(self, params):
        name = params.get("name")
        tool = self.tools().get(name) if isinstance(name, str) else None
        arguments = {}
        outcome = "denied"
        data = {"error": "Tool unavailable for this role"}
        if tool:
            try:
                arguments = tool.args.model_validate(params.get("arguments", {})).model_dump()
                data = getattr(self, tool.handler)(**arguments)
                outcome = "ok"
            except ValidationError:
                data = {"error": "Tool arguments failed validation"}
            except Exception:
                self.audit(name, arguments, "failed")
                raise
        self.audit(name if tool else "unavailable", arguments, outcome, data)
        return {"content": [{"type": "text", "text": json.dumps(data)}],
                "structuredContent": data, "isError": outcome != "ok"}


class McpClient:
    def __init__(self, server):
        self.server = server
        self.request_id = 0
        self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": {"name": "trinetra-worker", "version": "1.0.0"}})
        server.receive({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _request(self, method, params):
        self.request_id += 1
        response = self.server.receive({"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params})
        return response["result"]

    def tools(self):
        return self._request("tools/list", {})["tools"]

    def invoke(self, name, arguments=None):
        return self._request("tools/call", {"name": name, "arguments": {} if arguments is None else arguments})

    def read(self, name, **arguments):
        response = self.invoke(name, arguments)
        if response["isError"]:
            raise ValueError(response["structuredContent"]["error"])
        return response["structuredContent"]


def fastmcp_server(session):
    from fastmcp import FastMCP

    server = FastMCP(f"trinetra-{session.service or 'soc'}")
    client = McpClient(session)

    def bind(name):
        def read() -> dict:
            return client.read(name)
        return read

    def expand_graph(hops: int = 5) -> dict:
        return client.read("expand_graph", hops=hops)

    def explain_score(signal: Literal["voice", "coercion", "remarks", "gnn", "fusion"]) -> dict:
        return client.read("explain_score", signal=signal)

    special = {"expand_graph": expand_graph, "explain_score": explain_score}
    for name, tool in session.tools().items():
        if tool.read_only:
            server.tool(name=name, description=tool.description, annotations={"readOnlyHint": True})(
                special.get(name) or bind(name))
    return server


def main():
    from .ledger import open_ledger

    parser = argparse.ArgumentParser()
    parser.add_argument("case_id")
    parser.add_argument("--service", choices=("case", "evidence", "graph", "model"))
    parser.add_argument("--fastmcp", action="store_true")
    args = parser.parse_args()
    ledger = open_ledger()
    case = ledger.case(args.case_id)
    server = McpSession(ledger, case, "investigator", "stdio", service=args.service)
    if args.fastmcp:
        fastmcp_server(server).run(transport="stdio")
        return
    while line := sys.stdin.buffer.readline(65537):
        if len(line) > 65536:
            break
        try:
            response = server.receive(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeError):
            response = server.error(None, -32700, "Parse error")
        except Exception:
            response = server.error(None, -32603, "Internal error")
        if response is not None:
            print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
