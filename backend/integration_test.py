"""TRINETRA End-to-End System Integration Test.

Simulates live banking gateway operations:
1. Health & Config Handshake
2. Scenario Discovery & Preset Execution
3. All 4 Attack Feeds (Clean, Voice Clone, 5-Hop Mule Ring, Digital Arrest)
4. Sub-150ms Synchronous SLA Validation
5. Real-Time WebSocket Streaming & Cytoscape Telemetry
6. Operational SOC Analyst Overrides (Quarantine & Release)
7. Final Live Performance Metrics Verification
"""

import sys
import time
from tools.test_support import test_client
from app.main import app, graph_engine, metrics_store

def run_integration_test():
    print("=" * 75)
    print("  TRINETRA: END-TO-END SYSTEM INTEGRATION TEST")
    print("=" * 75)
    
    # 0. Initialize Test Client & Reset State
    client = test_client(app)
    graph_engine.reset()
    metrics_store["total_evaluated"] = 0
    metrics_store["allowed"] = 0
    metrics_store["stepped_up"] = 0
    metrics_store["held"] = 0
    metrics_store["total_latency_ms"] = 0.0
    print("[1/7] In-memory graph state and telemetry metrics initialized.")

    # 1. Health & Handshake Verification
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    health_data = res.json()
    assert health_data["status"] == "online"
    print(f"[2/7] Health check OK: Status='online', Target SLA={health_data['latency_target_ms']}ms.")

    # 2. Scenario Discovery
    res = client.get("/api/v1/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert len(scenarios) == 4
    print(f"[3/7] Scenario Discovery OK: Found {len(scenarios)} attack presets:")
    for sc in scenarios:
        print(f"      • [{sc['id']}] {sc['title']} -> Expected: {sc['expected_decision']} ({sc['channel']} ₹{sc['amount']:,.0f})")

    # 3. WebSocket Real-Time Stream Handshake
    print("[4/7] Testing Real-Time WebSocket Stream & Live Interceptions...")
    with client.websocket_connect("/ws/soc-stream") as ws:
        handshake = ws.receive_json()
        assert handshake["event_type"] == "CONNECTED"
        print("      ✓ WebSocket Handshake established.")

        # Test Ping/Pong
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        print("      ✓ WebSocket Keep-Alive Ping/Pong OK.")

        # Execute Scenario 1: Clean Baseline
        t0 = time.perf_counter()
        res_sc1 = client.post("/api/v1/scenarios/trigger/SCENARIO_1_BASELINE")
        sc1_data = res_sc1.json()
        sc1_latency = (time.perf_counter() - t0) * 1000.0
        assert sc1_data["actual_decision"] == "ALLOW"
        assert sc1_data["evaluation"]["composite_risk"] < 35.0
        event1 = ws.receive_json()
        assert event1["event_type"] == "TRANSACTION_EVALUATED"
        assert event1["decision"] == "ALLOW"
        print(f"      ✓ Scenario 1 (Clean Baseline): Decision='ALLOW', Risk={sc1_data['evaluation']['composite_risk']}, Latency={sc1_latency:.2f}ms (WS Event Broadcasted).")

        # Execute Scenario 2: CEO Voice Clone
        t0 = time.perf_counter()
        res_sc2 = client.post("/api/v1/scenarios/trigger/SCENARIO_2_VOICE_CLONE")
        sc2_data = res_sc2.json()
        sc2_latency = (time.perf_counter() - t0) * 1000.0
        assert sc2_data["actual_decision"] == "HOLD"
        assert sc2_data["evaluation"]["breakdown"]["acoustic_score"] >= 70.0
        assert sc2_data["evaluation"]["acoustic_diagnostics"]["is_synthetic"] is True
        event2 = ws.receive_json()
        assert event2["event_type"] == "TRANSACTION_EVALUATED"
        assert event2["decision"] == "HOLD"
        print(f"      ✓ Scenario 2 (CEO Voice Clone): Decision='HOLD', Acoustic Score={sc2_data['evaluation']['breakdown']['acoustic_score']}, Latency={sc2_latency:.2f}ms (Vocoder Flag=True).")

        # Execute Scenario 3: 5-Hop Mule Ring
        t0 = time.perf_counter()
        res_sc3 = client.post("/api/v1/scenarios/trigger/SCENARIO_3_MULE_RING")
        sc3_data = res_sc3.json()
        sc3_latency = (time.perf_counter() - t0) * 1000.0
        assert sc3_data["actual_decision"] == "HOLD"
        assert sc3_data["evaluation"]["breakdown"]["graph_score"] >= 70.0
        assert sc3_data["evaluation"]["graph_diagnostics"]["hop_count"] >= 4
        event3 = ws.receive_json()
        assert event3["event_type"] == "TRANSACTION_EVALUATED"
        assert "MULE-NODE-1" in event3["graph_diagnostics"]["quarantined_nodes"]
        print(f"      ✓ Scenario 3 (5-Hop Mule Ring): Decision='HOLD', Graph Score={sc3_data['evaluation']['breakdown']['graph_score']}, Hops={sc3_data['evaluation']['graph_diagnostics']['hop_count']}, Latency={sc3_latency:.2f}ms (Auto-Quarantine Active).")

        # Execute Scenario 4: Digital Arrest Extortion
        t0 = time.perf_counter()
        res_sc4 = client.post("/api/v1/scenarios/trigger/SCENARIO_4_DIGITAL_ARREST")
        sc4_data = res_sc4.json()
        sc4_latency = (time.perf_counter() - t0) * 1000.0
        assert sc4_data["actual_decision"] == "HOLD"
        assert sc4_data["evaluation"]["breakdown"]["nlp_score"] >= 70.0
        event4 = ws.receive_json()
        assert event4["event_type"] == "TRANSACTION_EVALUATED"
        print(f"      ✓ Scenario 4 (Digital Arrest): Decision='HOLD', NLP Score={sc4_data['evaluation']['breakdown']['nlp_score']}, Latency={sc4_latency:.2f}ms (Coercion Override Engaged).")

    # 4. Direct In-Line Banking Gateway Call
    print("[5/7] Testing Direct In-Line Banking Gateway Call (POST /api/v1/intercept)...")
    custom_tx = {
        "transaction_id": "TX-LIVE-E2E-777",
        "sender_account": "ACC-ENTERPRISE-PAYROLL",
        "recipient_account": "ACC-EMPLOYEE-BONUS",
        "amount": 150000.0,
        "channel": "IMPS",
        "recipient_account_age_days": 365,
        "narrative_context": "Annual performance bonus payout"
    }
    t0 = time.perf_counter()
    res_direct = client.post("/api/v1/intercept", json=custom_tx)
    direct_latency = (time.perf_counter() - t0) * 1000.0
    assert res_direct.status_code == 200
    direct_body = res_direct.json()
    assert direct_body["decision"] == "ALLOW"
    assert direct_body["latency_ms"] < 150.0
    print(f"      ✓ Direct Gateway Call: ID={direct_body['transaction_id']}, Decision='ALLOW', Server Latency={direct_body['latency_ms']}ms, Wall Clock={direct_latency:.2f}ms.")

    # 5. SOC Analyst Operational Override
    print("[6/7] Testing SOC Analyst Manual Freeze and Unfreeze Actions...")
    freeze_payload = {
        "account": "SUSPECT-ACCOUNT-X",
        "action": "CONFIRM_FREEZE",
        "analyst_id": "CHIEF-SOC-OFFICER"
    }
    res_freeze = client.post("/api/v1/soc/override", json=freeze_payload)
    assert res_freeze.status_code == 200
    assert res_freeze.json()["currently_quarantined"] is True
    assert "SUSPECT-ACCOUNT-X" in graph_engine.quarantined_accounts
    print("      ✓ Analyst Freezed 'SUSPECT-ACCOUNT-X' -> Account Quarantined.")

    # Test that subsequent transaction targeting SUSPECT-ACCOUNT-X is immediately blocked
    blocked_tx = {
        "transaction_id": "TX-PROBE-BLOCKED",
        "sender_account": "VICTIM-PROBE",
        "recipient_account": "SUSPECT-ACCOUNT-X",
        "amount": 50000.0,
        "channel": "UPI"
    }
    res_blocked = client.post("/api/v1/intercept", json=blocked_tx)
    assert res_blocked.json()["decision"] == "HOLD"
    assert res_blocked.json()["composite_risk"] == 100.0
    print("      ✓ Probe transaction to quarantined account immediately blocked with 100.0 risk penalty.")

    # Analyst unfreezes
    unfreeze_payload = {
        "account": "SUSPECT-ACCOUNT-X",
        "action": "RELEASE_HOLD",
        "analyst_id": "CHIEF-SOC-OFFICER"
    }
    res_unfreeze = client.post("/api/v1/soc/override", json=unfreeze_payload)
    assert res_unfreeze.status_code == 200
    assert res_unfreeze.json()["currently_quarantined"] is False
    print("      ✓ Analyst Released 'SUSPECT-ACCOUNT-X' from Quarantine.")

    # 6. Final Metrics Audit
    print("[7/7] Auditing Operational Metrics and Latency SLA Compliance...")
    metrics_res = client.get("/api/v1/metrics")
    assert metrics_res.status_code == 200
    metrics = metrics_res.json()
    print(f"      • Total Evaluated Transactions: {metrics['total_evaluated']}")
    print(f"      • Allowed Payments:             {metrics['allowed']}")
    print(f"      • Intercepted & Held Scams:     {metrics['held']}")
    print(f"      • Average Server Latency:       {metrics['average_latency_ms']:.2f} ms")
    assert metrics["total_evaluated"] >= 6
    assert metrics["held"] >= 4
    assert metrics["allowed"] >= 2
    assert metrics["average_latency_ms"] < 150.0

    print("=" * 75)
    print("  ALL INTEGRATION TESTS PASSED: SYSTEM IS 100% OPERATIONAL")
    print("=" * 75)
    return True

if __name__ == "__main__":
    success = run_integration_test()
    sys.exit(0 if success else 1)
