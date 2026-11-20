import pytest
from tools.test_support import test_client
from app.main import app, graph_engine, metrics_store
from app.config import MAX_INTERCEPT_LATENCY_MS

@pytest.fixture
def client():
    # Reset in-memory state before tests
    graph_engine.reset()
    metrics_store["total_evaluated"] = 0
    metrics_store["allowed"] = 0
    metrics_store["stepped_up"] = 0
    metrics_store["held"] = 0
    metrics_store["total_latency_ms"] = 0.0
    return test_client(app)

# ============================================================================
# 1. Preset Scenarios API Tests
# ============================================================================

def test_list_scenarios_returns_four_presets(client):
    """GET /api/v1/scenarios must list all 4 demo scenarios."""
    res = client.get("/api/v1/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert len(scenarios) == 4
    scenario_ids = [s["id"] for s in scenarios]
    assert "SCENARIO_1_BASELINE" in scenario_ids
    assert "SCENARIO_2_VOICE_CLONE" in scenario_ids
    assert "SCENARIO_3_MULE_RING" in scenario_ids
    assert "SCENARIO_4_DIGITAL_ARREST" in scenario_ids

def test_trigger_scenario_1_clean_payment(client):
    """Scenario 1 (Clean Baseline) must result in ALLOW."""
    res = client.post("/api/v1/scenarios/trigger/SCENARIO_1_BASELINE")
    assert res.status_code == 200
    data = res.json()
    assert data["matches_expectation"] is True
    assert data["actual_decision"] == "ALLOW"
    assert data["evaluation"]["composite_risk"] < 35.0
    assert data["evaluation"]["latency_ms"] < MAX_INTERCEPT_LATENCY_MS

def test_trigger_scenario_2_ceo_voice_clone(client):
    """Scenario 2 (Voice Clone) must result in HOLD with critical acoustic score."""
    res = client.post("/api/v1/scenarios/trigger/SCENARIO_2_VOICE_CLONE")
    assert res.status_code == 200
    data = res.json()
    assert data["matches_expectation"] is True
    assert data["actual_decision"] == "HOLD"
    eval_data = data["evaluation"]
    assert eval_data["breakdown"]["acoustic_score"] >= 70.0
    assert eval_data["acoustic_diagnostics"]["is_synthetic"] is True

def test_trigger_scenario_3_five_hop_mule_ring(client):
    """Scenario 3 (5-Hop Mule Ring) must result in HOLD with multi-hop graph alert."""
    res = client.post("/api/v1/scenarios/trigger/SCENARIO_3_MULE_RING")
    assert res.status_code == 200
    data = res.json()
    assert data["matches_expectation"] is True
    assert data["actual_decision"] == "HOLD"
    eval_data = data["evaluation"]
    assert eval_data["breakdown"]["graph_score"] >= 70.0
    assert eval_data["graph_diagnostics"]["is_mule_ring"] is True
    assert eval_data["graph_diagnostics"]["hop_count"] >= 4

def test_trigger_scenario_4_digital_arrest(client):
    """Scenario 4 (Digital Arrest Extortion) must result in HOLD with high NLP score."""
    res = client.post("/api/v1/scenarios/trigger/SCENARIO_4_DIGITAL_ARREST")
    assert res.status_code == 200
    data = res.json()
    assert data["matches_expectation"] is True
    assert data["actual_decision"] == "HOLD"
    eval_data = data["evaluation"]
    assert eval_data["breakdown"]["nlp_score"] >= 70.0

def test_trigger_nonexistent_scenario_404(client):
    """Triggering unknown scenario ID must return HTTP 404."""
    res = client.post("/api/v1/scenarios/trigger/NON_EXISTENT_SCENARIO")
    assert res.status_code == 404

# ============================================================================
# 2. In-Line Gateway & Latency SLA Tests
# ============================================================================

def test_direct_intercept_endpoint_latency_sla(client):
    """POST /api/v1/intercept must evaluate end-to-end within 150ms."""
    payload = {
        "transaction_id": "TX-INLINE-990",
        "sender_account": "ACC-SENDER-1",
        "recipient_account": "ACC-RECEIVER-2",
        "amount": 45000.0,
        "channel": "UPI",
        "narrative_context": "Direct in-line test payment",
        "recipient_account_age_days": 180
    }
    res = client.post("/api/v1/intercept", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["transaction_id"] == "TX-INLINE-990"
    assert data["decision"] in ["ALLOW", "STEP_UP", "HOLD"]
    assert data["latency_ms"] < MAX_INTERCEPT_LATENCY_MS

# ============================================================================
# 3. SOC Analyst Manual Override & Quarantine Tests
# ============================================================================

def test_soc_analyst_override_freeze_and_release(client):
    """Analyst override must freeze account, then release it."""
    # 1. Freeze
    freeze_req = {
        "account": "MULE-ROGUE-99",
        "action": "CONFIRM_FREEZE",
        "analyst_id": "ANALYST-CHIEF-1"
    }
    res = client.post("/api/v1/soc/override", json=freeze_req)
    assert res.status_code == 200
    assert res.json()["currently_quarantined"] is True
    assert "MULE-ROGUE-99" in graph_engine.quarantined_accounts

    # 2. Release
    release_req = {
        "account": "MULE-ROGUE-99",
        "action": "RELEASE_HOLD",
        "analyst_id": "ANALYST-CHIEF-1"
    }
    res = client.post("/api/v1/soc/override", json=release_req)
    assert res.status_code == 200
    assert res.json()["currently_quarantined"] is False
    assert "MULE-ROGUE-99" not in graph_engine.quarantined_accounts

def test_soc_override_invalid_action(client):
    res = client.post("/api/v1/soc/override", json={"account": "ACC-1", "action": "INVALID_ACTION"})
    assert res.status_code == 400

# ============================================================================
# 4. Metrics & Performance Telemetry Tests
# ============================================================================

def test_metrics_counter_increments(client):
    """Triggering transactions must accurately increment the metrics telemetry."""
    # Run one clean and one attack
    client.post("/api/v1/scenarios/trigger/SCENARIO_1_BASELINE")
    client.post("/api/v1/scenarios/trigger/SCENARIO_2_VOICE_CLONE")

    res = client.get("/api/v1/metrics")
    assert res.status_code == 200
    metrics = res.json()
    assert metrics["total_evaluated"] >= 2
    assert metrics["allowed"] >= 1
    assert metrics["held"] >= 1
    assert metrics["average_latency_ms"] < MAX_INTERCEPT_LATENCY_MS

# ============================================================================
# 5. Real-Time WebSocket Streaming Tests
# ============================================================================

def test_websocket_soc_stream_broadcast(client):
    """WebSocket client receives handshake and live TRANSACTION_EVALUATED events."""
    with client.websocket_connect("/ws/soc-stream") as websocket:
        # Handshake
        handshake = websocket.receive_json()
        assert handshake["event_type"] == "CONNECTED"

        # Ping-Pong check
        websocket.send_text("ping")
        pong = websocket.receive_text()
        assert pong == "pong"

        # Trigger a scenario via HTTP while WS is connected
        client.post("/api/v1/scenarios/trigger/SCENARIO_1_BASELINE")

        # WS must receive broadcast event
        event = websocket.receive_json()
        assert event["event_type"] == "TRANSACTION_EVALUATED"
        assert event["decision"] == "ALLOW"
        assert "cytoscape_subgraph" in event
        assert "breakdown" in event
