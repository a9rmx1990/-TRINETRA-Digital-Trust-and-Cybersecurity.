import time
import pytest
import numpy as np
from app.engines.nlp_engine import CoerciveContextEngine
from app.engines.policy_engine import PolicyDecisionEngine
from app.schemas import DecisionType, RiskBreakdown

@pytest.fixture
def nlp_engine():
    return CoerciveContextEngine()

@pytest.fixture
def policy_engine():
    return PolicyDecisionEngine()

# ============================================================================
# 1. NLP Coercive Context Engine Tests
# ============================================================================

def test_nlp_empty_and_neutral_context(nlp_engine):
    """Empty or everyday benign transfer remarks must score 0 risk."""
    for text in [None, "", "   ", "Monthly apartment rent", "Lunch with Priya", "Diwali gift for family"]:
        score, reasons, matched = nlp_engine.analyze(text)
        assert score == 0.0
        assert len(matched) == 0

def test_nlp_digital_arrest_script_detected(nlp_engine):
    """Full-blown Digital Arrest extortion script must trigger critical NLP risk (>= 80)."""
    script = (
        "This is CBI Cyber Police Inspector Sharma. You are under Digital Arrest for a narcotics money laundering case. "
        "Do not disconnect call or inform family. Immediately transfer funds to Safe State Escrow Verification Account."
    )
    score, reasons, matched = nlp_engine.analyze(script)
    assert score >= 80.0
    assert "AUTHORITY_IMPERSONATION" in matched
    assert "FRAUDULENT_ROUTING" in matched
    assert "COERCIVE_URGENCY" in matched
    assert any("authority impersonation" in r.lower() for r in reasons)
    assert any("coercive urgency" in r.lower() for r in reasons)

def test_nlp_single_category_authority_cues(nlp_engine):
    """Targeted authority cue alone scores moderate anomaly."""
    score, _, matched = nlp_engine.analyze("Supreme Court summons and non-bailable warrant issued.")
    assert score >= 40.0
    assert "AUTHORITY_IMPERSONATION" in matched

def test_nlp_safe_escrow_routing_cues(nlp_engine):
    """Fraudulent safe escrow phrasing scores anomaly."""
    score, _, matched = nlp_engine.analyze("Transfer to Safe Government Account for clearance.")
    assert score >= 35.0
    assert "FRAUDULENT_ROUTING" in matched

# ============================================================================
# 2. Unified Policy Engine Decision Tests
# ============================================================================

def test_policy_clean_baseline_allow(policy_engine):
    """All zero forensic signals output ALLOW."""
    decision, score, reasons, breakdown = policy_engine.evaluate(
        acoustic_score=0.0,
        graph_score=0.0,
        nlp_score=0.0,
        reasons_audio=[],
        reasons_graph=[],
        reasons_nlp=[]
    )
    assert decision == "ALLOW"
    assert score == 0.0
    assert breakdown.composite_risk == 0.0
    assert any("Fast-path cleared" in r for r in reasons)

def test_policy_step_up_friction(policy_engine):
    """Intermediate composite risk (35 - 69.9) injects STEP_UP challenge."""
    # 0.45*40 + 0.40*45 + 0.15*60 = 18 + 18 + 9 = 45.0
    decision, score, reasons, _ = policy_engine.evaluate(
        acoustic_score=40.0,
        graph_score=45.0,
        nlp_score=60.0,
        reasons_audio=["Mild acoustic anomaly"],
        reasons_graph=["Multi-hop transfer"],
        reasons_nlp=["Urgency detected"]
    )
    assert decision == "STEP_UP"
    assert 35.0 <= score < 70.0
    assert any("Dynamic friction injected" in r for r in reasons)

def test_policy_critical_composite_hold(policy_engine):
    """Elevated composite risk (>= 70) automatically triggers HOLD."""
    # 0.45*80 + 0.40*85 + 0.15*80 = 36 + 34 + 12 = 82.0
    decision, score, reasons, _ = policy_engine.evaluate(
        acoustic_score=80.0,
        graph_score=85.0,
        nlp_score=80.0,
        reasons_audio=["Vocoder synthetic artifacts"],
        reasons_graph=["5-hop mule chain"],
        reasons_nlp=["Digital arrest script"]
    )
    assert decision == "HOLD"
    assert score >= 70.0
    assert any("Transaction frozen" in r for r in reasons)

def test_policy_voice_clone_extreme_override(policy_engine):
    """Even if graph and nlp are 0, a 90.0 voice clone triggers HOLD via override."""
    decision, score, reasons, _ = policy_engine.evaluate(
        acoustic_score=90.0,
        graph_score=0.0,
        nlp_score=0.0,
        reasons_audio=["Synthetic vocoder detected"],
        reasons_graph=[],
        reasons_nlp=[]
    )
    assert decision == "HOLD"
    assert score >= 70.0
    assert any("HIGH-PRIORITY OVERRIDE: Forensic voice clone" in r for r in reasons)

def test_policy_mule_ring_extreme_override(policy_engine):
    """Even if audio and nlp are 0, a 90.0 mule ring triggers HOLD via override."""
    decision, score, reasons, _ = policy_engine.evaluate(
        acoustic_score=0.0,
        graph_score=90.0,
        nlp_score=0.0,
        reasons_audio=[],
        reasons_graph=["Rapid dispersion velocity"],
        reasons_nlp=[]
    )
    assert decision == "HOLD"
    assert score >= 70.0
    assert any("HIGH-PRIORITY OVERRIDE: Active multi-hop money-mule" in r for r in reasons)

def test_policy_quarantine_absolute_veto(policy_engine):
    """Counterparty on quarantine list must immediately yield 100.0 HOLD."""
    decision, score, reasons, breakdown = policy_engine.evaluate(
        acoustic_score=10.0,
        graph_score=10.0,
        nlp_score=0.0,
        reasons_audio=[],
        reasons_graph=["Account on blacklist"],
        reasons_nlp=[],
        is_quarantined=True
    )
    assert decision == "HOLD"
    assert score == 100.0
    assert breakdown.graph_score == 100.0
    assert any("permanently quarantined" in r for r in reasons)

def test_policy_exact_threshold_boundary_transitions():
    """Verify exact policy boundary steps at 34.9, 35.0, 69.9, and 70.0."""
    eng = PolicyDecisionEngine(weight_acoustic=1.0, weight_graph=0.0, weight_nlp=0.0)
    
    # Below 35.0 -> ALLOW
    dec, _, _, _ = eng.evaluate(34.9, 0, 0, [], [], [])
    assert dec == "ALLOW"

    # Exactly 35.0 -> STEP_UP
    dec, _, _, _ = eng.evaluate(35.0, 0, 0, [], [], [])
    assert dec == "STEP_UP"

    # At 69.9 -> STEP_UP
    dec, _, _, _ = eng.evaluate(69.9, 0, 0, [], [], [])
    assert dec == "STEP_UP"

    # At 70.0 -> HOLD
    dec, _, _, _ = eng.evaluate(70.0, 0, 0, [], [], [])
    assert dec == "HOLD"

# ============================================================================
# 3. Execution Latency Benchmark (< 1.0 ms)
# ============================================================================

def test_policy_and_nlp_latency_under_5ms(nlp_engine, policy_engine):
    """Coercion scanning and risk aggregation combined must run in < 5ms."""
    text = "CBI Digital Arrest non-bailable warrant. Immediate transfer to Safe Government Escrow."
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        nlp_s, nlp_r, _ = nlp_engine.analyze(text)
        dec, score, r, _ = policy_engine.evaluate(85.0, 75.0, nlp_s, [], [], nlp_r)
        dt = (time.perf_counter() - t0) * 1000.0
        times.append(dt)

    avg_ms = np.mean(times)
    max_ms = np.max(times)
    print(f"\n[NLP & Policy Benchmark] Combined Latency: Average: {avg_ms:.3f}ms, Max: {max_ms:.3f}ms")
    assert avg_ms < 5.0
