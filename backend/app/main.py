import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import MAX_INTERCEPT_LATENCY_MS
from app.schemas import (
    TransactionPayload,
    InterceptionResponse,
    RiskBreakdown,
    AcousticDiagnostics,
    GraphDiagnostics,
    SOCEvent
)
from app.engines import (
    AudioForensicsEngine,
    GraphIntelligenceEngine,
    CoerciveContextEngine,
    PolicyDecisionEngine
)
from app.simulator.scenarios import get_scenarios, get_scenario_by_id
from app.websocket_manager import ws_manager
from app.live.api import router as sandbox_router

app = FastAPI(
    title="TRINETRA: Digital Trust & Cybersecurity Middleware",
    description="Real-Time Autonomous Interception of Generative AI Cyber Fraud and Mule Networks",
    version="1.0.0"
)

app.include_router(sandbox_router)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Engine Singletons
audio_engine = AudioForensicsEngine(sample_rate=16000)
graph_engine = GraphIntelligenceEngine()
nlp_engine = CoerciveContextEngine()
policy_engine = PolicyDecisionEngine()

# Metrics Tracker
metrics_store = {
    "total_evaluated": 0,
    "allowed": 0,
    "stepped_up": 0,
    "held": 0,
    "total_latency_ms": 0.0
}

# Request schema for analyst manual override
class AnalystOverrideRequest(BaseModel):
    account: str = Field(..., min_length=1)
    action: str = Field(..., description="CONFIRM_FREEZE | RELEASE_HOLD")
    analyst_id: Optional[str] = "SOC-ANALYST-1"
    note: Optional[str] = "Manual operational intervention"

# ----------------------------------------------------------------------------
# System & Health Endpoints
# ----------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "online",
        "service": "trinetra-middleware",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_target_ms": MAX_INTERCEPT_LATENCY_MS,
        "active_ws_clients": len(ws_manager.active_connections)
    }

@app.get("/api/v1/metrics")
def get_metrics():
    total = metrics_store["total_evaluated"]
    avg_latency = (metrics_store["total_latency_ms"] / total) if total > 0 else 0.0
    return {
        "total_evaluated": total,
        "allowed": metrics_store["allowed"],
        "stepped_up": metrics_store["stepped_up"],
        "held": metrics_store["held"],
        "average_latency_ms": round(avg_latency, 2),
        "quarantined_accounts_count": len(graph_engine.quarantined_accounts)
    }

# ----------------------------------------------------------------------------
# Core Interception Logic Helper
# ----------------------------------------------------------------------------

async def evaluate_transaction_internal(payload: TransactionPayload) -> InterceptionResponse:
    t0 = time.perf_counter()

    # 1. Check existing quarantine status
    is_quarantined = (
        payload.sender_account in graph_engine.quarantined_accounts or
        payload.recipient_account in graph_engine.quarantined_accounts
    )

    # 2. Run Forensic Engines in Parallel Pipeline
    # A. Acoustic Analysis
    acoustic_score, acoustic_diag, acoustic_reasons = audio_engine.analyze(payload.audio_base64)

    # B. Graph Topology Analysis
    graph_score, graph_diag, graph_reasons, cytoscape_graph = graph_engine.analyze(
        sender=payload.sender_account,
        recipient=payload.recipient_account,
        amount=payload.amount,
        recipient_age_days=payload.recipient_account_age_days,
        tx_id=payload.transaction_id
    )

    # C. Coercive Context NLP Analysis
    nlp_score, nlp_reasons, nlp_matches = nlp_engine.analyze(payload.narrative_context)

    # 3. Dynamic Policy Decision Gating
    decision, composite_risk, consolidated_reasons, breakdown = policy_engine.evaluate(
        acoustic_score=acoustic_score,
        graph_score=graph_score,
        nlp_score=nlp_score,
        reasons_audio=acoustic_reasons,
        reasons_graph=graph_reasons,
        reasons_nlp=nlp_reasons,
        is_quarantined=is_quarantined
    )

    # Ensure critical risk accounts are quarantined immediately
    if decision == "HOLD":
        graph_engine.quarantine_account(payload.recipient_account)
        if payload.recipient_account not in graph_diag.quarantined_nodes:
            graph_diag.quarantined_nodes.append(payload.recipient_account)

    # Refresh Cytoscape topology with updated quarantine highlights
    cytoscape_graph = graph_engine.extract_subgraph_cytoscape(payload.recipient_account, radius=2)

    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    # Update Metrics
    metrics_store["total_evaluated"] += 1
    metrics_store["total_latency_ms"] += latency_ms
    if decision == "ALLOW":
        metrics_store["allowed"] += 1
    elif decision == "STEP_UP":
        metrics_store["stepped_up"] += 1
    else:
        metrics_store["held"] += 1

    response = InterceptionResponse(
        transaction_id=payload.transaction_id,
        decision=decision,
        composite_risk=composite_risk,
        latency_ms=latency_ms,
        reasons=consolidated_reasons,
        breakdown=breakdown,
        acoustic_diagnostics=acoustic_diag,
        graph_diagnostics=graph_diag
    )

    # Broadcast event to all active SOC dashboards
    event_payload = {
        "event_type": "TRANSACTION_EVALUATED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transaction": payload.model_dump(exclude={"audio_base64"}),
        "decision": decision,
        "composite_risk": composite_risk,
        "latency_ms": latency_ms,
        "reasons": consolidated_reasons,
        "breakdown": breakdown.model_dump(),
        "acoustic_diagnostics": acoustic_diag.model_dump(),
        "graph_diagnostics": graph_diag.model_dump(),
        "cytoscape_subgraph": cytoscape_graph
    }
    await ws_manager.broadcast(event_payload)

    return response

# ----------------------------------------------------------------------------
# In-Line Banking Gateway Hook
# ----------------------------------------------------------------------------

@app.post("/api/v1/intercept", response_model=InterceptionResponse)
async def intercept_transaction(payload: TransactionPayload):
    """Sub-150ms synchronous banking interceptor gateway."""
    return await evaluate_transaction_internal(payload)

# ----------------------------------------------------------------------------
# Graph & Topology Inspection
# ----------------------------------------------------------------------------

@app.get("/api/v1/graph/mule-network")
def get_graph_topology(focus_account: Optional[str] = None):
    """Returns Cytoscape.js formatted graph topology."""
    if focus_account:
        return graph_engine.extract_subgraph_cytoscape(focus_account, radius=2)
    # Default to first available node or generic root
    nodes = list(graph_engine.graph.nodes())
    root = nodes[0] if nodes else "ROOT-NODE"
    return graph_engine.extract_subgraph_cytoscape(root, radius=3)

# ----------------------------------------------------------------------------
# SOC Analyst Manual Overrides
# ----------------------------------------------------------------------------

@app.post("/api/v1/soc/override")
async def soc_analyst_override(req: AnalystOverrideRequest):
    """Manual analyst operational freeze or release."""
    if req.action == "CONFIRM_FREEZE":
        graph_engine.quarantine_account(req.account)
        status_msg = f"Account [{req.account}] permanently locked by {req.analyst_id}."
    elif req.action == "RELEASE_HOLD":
        graph_engine.release_quarantine(req.account)
        status_msg = f"Account [{req.account}] released from quarantine by {req.analyst_id}."
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be CONFIRM_FREEZE or RELEASE_HOLD.")

    # Broadcast override event
    await ws_manager.broadcast({
        "event_type": "ANALYST_OVERRIDE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account": req.account,
        "action": req.action,
        "analyst_id": req.analyst_id,
        "note": req.note,
        "status_message": status_msg
    })

    return {
        "status": "SUCCESS",
        "account": req.account,
        "action": req.action,
        "message": status_msg,
        "currently_quarantined": req.account in graph_engine.quarantined_accounts
    }

# ----------------------------------------------------------------------------
# Attack Simulator Presets
# ----------------------------------------------------------------------------

@app.get("/api/v1/scenarios")
def list_scenarios():
    """Lists the 4 available attack demonstration feeds."""
    scenarios = get_scenarios()
    return [
        {
            "id": sc["id"],
            "title": sc["title"],
            "description": sc["description"],
            "expected_decision": sc["expected_decision"],
            "expected_risk_range": sc["expected_risk_range"],
            "channel": sc["payload"]["channel"],
            "amount": sc["payload"]["amount"]
        }
        for sc in scenarios.values()
    ]

@app.post("/api/v1/scenarios/trigger/{scenario_id}")
async def trigger_scenario(scenario_id: str):
    """Executes a demo scenario, configuring graph topology and evaluating payload."""
    sc = get_scenario_by_id(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")

    # 1. Execute scenario setup actions (e.g. pre-configuring multi-hop mule path)
    for action in sc.get("setup_actions", []):
        graph_engine.add_transaction(
            sender=action["sender"],
            recipient=action["recipient"],
            amount=action["amount"],
            recipient_age_days=action.get("age_days", 5)
        )

    # 2. Ingest payload and evaluate
    payload = TransactionPayload(**sc["payload"])
    evaluation_result = await evaluate_transaction_internal(payload)

    return {
        "scenario_id": sc["id"],
        "title": sc["title"],
        "expected_decision": sc["expected_decision"],
        "actual_decision": evaluation_result.decision,
        "matches_expectation": evaluation_result.decision == sc["expected_decision"],
        "evaluation": evaluation_result
    }

# ----------------------------------------------------------------------------
# WebSocket Real-Time Stream
# ----------------------------------------------------------------------------

@app.websocket("/ws/soc-stream")
async def websocket_soc_endpoint(websocket: WebSocket):
    """Real-time bi-directional WebSocket feed for live SOC alert streaming."""
    await ws_manager.connect(websocket)
    try:
        # Send initial handshake message
        await websocket.send_json({
            "event_type": "CONNECTED",
            "message": "Connected to TRINETRA SOC Real-Time Stream",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "quarantined_count": len(graph_engine.quarantined_accounts)
        })
        while True:
            # Keep connection alive; accept optional ping or analyst commands
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

