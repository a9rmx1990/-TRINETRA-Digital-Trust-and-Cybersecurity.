import time
import pytest
import numpy as np
from app.engines.graph_engine import GraphIntelligenceEngine

@pytest.fixture
def engine():
    eng = GraphIntelligenceEngine()
    eng.reset()
    return eng

# ============================================================================
# 1. Baseline Clean Transaction Tests
# ============================================================================

def test_clean_single_hop_transaction_low_risk(engine):
    """Standard transfer between mature accounts should produce low risk (< 30)."""
    score, diag, reasons, cytoscape = engine.analyze(
        sender="ACC-ALICE-100",
        recipient="ACC-BOB-200",
        amount=15000.0,
        recipient_age_days=300
    )
    assert score < 30.0
    assert diag.is_mule_ring is False
    assert diag.cycle_detected is False
    assert diag.hop_count == 1
    assert "Normal low-degree, single-hop" in reasons[0]
    assert len(cytoscape["nodes"]) >= 2
    assert len(cytoscape["edges"]) >= 1

# ============================================================================
# 2. 5-Hop Rapid Mule Ring Detection Tests
# ============================================================================

def test_five_hop_mule_network_detected(engine):
    """Sequential fund dispersion across 5 hops must trigger critical mule alarm."""
    # Pre-populate 4 downstream hops from MULE-1
    engine.add_transaction("MULE-1", "MULE-2", amount=95000.0, recipient_age_days=5)
    engine.add_transaction("MULE-2", "MULE-3", amount=90000.0, recipient_age_days=4)
    engine.add_transaction("MULE-3", "MULE-4", amount=85000.0, recipient_age_days=3)
    engine.add_transaction("MULE-4", "MULE-5", amount=80000.0, recipient_age_days=2)

    # Now victim sends initial transfer to MULE-1
    score, diag, reasons, cytoscape = engine.analyze(
        sender="VICTIM-99",
        recipient="MULE-1",
        amount=100000.0,
        recipient_age_days=5,
        tx_id="TX-VICTIM-01"
    )

    assert score >= 70.0, f"5-hop mule chain missed; score: {score}"
    assert diag.is_mule_ring is True
    assert diag.hop_count >= 4
    assert any("multi-hop" in r.lower() for r in reasons)
    assert "MULE-1" in engine.quarantined_accounts

# ============================================================================
# 3. Circular Laundering (Cycle Detection) Tests
# ============================================================================

def test_circular_routing_cycle_detected(engine):
    """Funds routed in a loop (A -> B -> C -> A) must be flagged with cycle alarm."""
    engine.add_transaction("ACC-RING-B", "ACC-RING-C", amount=50000.0)
    engine.add_transaction("ACC-RING-C", "ACC-RING-A", amount=48000.0)

    score, diag, reasons, _ = engine.analyze(
        sender="ACC-RING-A",
        recipient="ACC-RING-B",
        amount=52000.0,
        recipient_age_days=60
    )

    assert diag.cycle_detected is True
    assert score >= 60.0
    assert any("circular fund laundering loop" in r.lower() for r in reasons)

# ============================================================================
# 4. Dispersion Velocity Tests
# ============================================================================

def test_high_dispersion_velocity_spike(engine):
    """Account dumping 95% of incoming funds immediately must show high V_disp."""
    now = time.time()
    # Account receives money
    engine.add_transaction("SRC-01", "ACC-PASS-THROUGH", amount=100000.0, timestamp=now - 30)
    # Account immediately drains money to multiple recipients
    engine.add_transaction("ACC-PASS-THROUGH", "CASH-OUT-1", amount=45000.0, timestamp=now - 20)
    engine.add_transaction("ACC-PASS-THROUGH", "CASH-OUT-2", amount=50000.0, timestamp=now - 10)

    velocity = engine.calculate_dispersion_velocity("ACC-PASS-THROUGH")
    assert velocity > 1.0, f"Dispersion velocity expected > 1.0, got {velocity}"

# ============================================================================
# 5. Quarantine Gating Tests
# ============================================================================

def test_quarantined_account_receives_maximum_penalty(engine):
    """Any transfer to an account already on the quarantine list gets 100.0 risk."""
    engine.quarantine_account("FROZEN-MULE-44")
    
    score, diag, reasons, _ = engine.analyze(
        sender="UNSUSPECTING-USER",
        recipient="FROZEN-MULE-44",
        amount=25000.0
    )
    assert score == 100.0
    assert any("quarantine/freeze list" in r for r in reasons)

def test_release_quarantine(engine):
    """Manual analyst unfreeze releases account from quarantine."""
    engine.quarantine_account("ACC-LOCKED")
    assert "ACC-LOCKED" in engine.quarantined_accounts
    engine.release_quarantine("ACC-LOCKED")
    assert "ACC-LOCKED" not in engine.quarantined_accounts

# ============================================================================
# 6. Cytoscape Topology Structure & Latency Tests
# ============================================================================

def test_cytoscape_subgraph_schema(engine):
    """Extracted subgraph must strictly conform to Cytoscape.js {nodes, edges} format."""
    engine.add_transaction("A", "B", amount=1000.0)
    engine.add_transaction("B", "C", amount=900.0)
    
    cytoscape = engine.extract_subgraph_cytoscape("B", radius=2)
    assert "nodes" in cytoscape
    assert "edges" in cytoscape
    
    node_ids = [n["data"]["id"] for n in cytoscape["nodes"]]
    assert "A" in node_ids and "B" in node_ids and "C" in node_ids
    
    for edge in cytoscape["edges"]:
        assert "source" in edge["data"]
        assert "target" in edge["data"]
        assert "amount" in edge["data"]

def test_graph_engine_latency_under_10ms(engine):
    """Graph traversal, cycle detection, and serialization must execute in < 10ms."""
    # Build a 20-node synthetic network
    for i in range(1, 20):
        engine.add_transaction(f"NODE-{i}", f"NODE-{i+1}", amount=1000.0 * i)

    # Warmup
    engine.analyze("NODE-1", "NODE-2", amount=5000.0)

    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        engine.analyze("NODE-10", "NODE-11", amount=5000.0)
        dt = (time.perf_counter() - t0) * 1000.0
        times.append(dt)

    avg_ms = np.mean(times)
    max_ms = np.max(times)
    print(f"\n[Graph Engine Benchmark] Average: {avg_ms:.2f}ms, Max: {max_ms:.2f}ms")
    assert avg_ms < 10.0, f"Graph engine average latency exceeded 10ms: {avg_ms:.2f}ms"
