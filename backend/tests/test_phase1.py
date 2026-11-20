import pytest
from tools.test_support import test_client
from pydantic import ValidationError
from app.main import app
from app.schemas import (
    TransactionPayload,
    InterceptionResponse,
    RiskBreakdown,
    AcousticDiagnostics,
    GraphDiagnostics
)
from app.config import (
    THRESHOLD_ALLOW_MAX,
    THRESHOLD_STEP_UP_MAX,
    WEIGHT_ACOUSTIC,
    WEIGHT_GRAPH,
    WEIGHT_NLP,
    MAX_INTERCEPT_LATENCY_MS
)

@pytest.fixture
def client():
    return test_client(app)

# ============================================================================
# 1. Configuration Invariant Tests
# ============================================================================

def test_config_weights_sum_to_one():
    """Weights across the 3 forensic engines must strictly sum to 1.0."""
    total_weight = WEIGHT_ACOUSTIC + WEIGHT_GRAPH + WEIGHT_NLP
    assert round(total_weight, 4) == 1.0000, f"Weights sum to {total_weight}, expected 1.0"

def test_config_threshold_ordering():
    """ALLOW threshold must be strictly lower than STEP_UP threshold."""
    assert 0.0 < THRESHOLD_ALLOW_MAX < THRESHOLD_STEP_UP_MAX < 100.0
    assert MAX_INTERCEPT_LATENCY_MS > 0

# ============================================================================
# 2. Schema Validation & Boundary Tests
# ============================================================================

def test_valid_transaction_payload():
    payload = TransactionPayload(
        transaction_id="TX-2026-001",
        sender_account="ACC-ALICE-12",
        recipient_account="ACC-BOB-99",
        amount=50000.0,
        channel="UPI",
        narrative_context="Monthly vendor settlement",
        recipient_account_age_days=180
    )
    assert payload.transaction_id == "TX-2026-001"
    assert payload.amount == 50000.0
    assert payload.channel == "UPI"

def test_transaction_payload_negative_amount_rejected():
    with pytest.raises(ValidationError):
        TransactionPayload(
            transaction_id="TX-FAIL-1",
            sender_account="ACC-1",
            recipient_account="ACC-2",
            amount=-100.0
        )

def test_transaction_payload_zero_amount_rejected():
    with pytest.raises(ValidationError):
        TransactionPayload(
            transaction_id="TX-FAIL-2",
            sender_account="ACC-1",
            recipient_account="ACC-2",
            amount=0.0
        )

def test_transaction_payload_invalid_channel_rejected():
    with pytest.raises(ValidationError):
        TransactionPayload(
            transaction_id="TX-FAIL-3",
            sender_account="ACC-1",
            recipient_account="ACC-2",
            amount=500.0,
            channel="INVALID_BITCOIN_CHANNEL"
        )

def test_transaction_payload_empty_strings_rejected():
    with pytest.raises(ValidationError):
        TransactionPayload(
            transaction_id="",
            sender_account="ACC-1",
            recipient_account="ACC-2",
            amount=500.0
        )

def test_risk_breakdown_bounds():
    # Valid bounds [0.0, 100.0]
    valid_breakdown = RiskBreakdown(
        acoustic_score=92.5,
        graph_score=88.0,
        nlp_score=15.0,
        composite_risk=82.0
    )
    assert valid_breakdown.composite_risk == 82.0

    # Out-of-bounds score should raise ValidationError
    with pytest.raises(ValidationError):
        RiskBreakdown(acoustic_score=105.0)

    with pytest.raises(ValidationError):
        RiskBreakdown(composite_risk=-1.0)

def test_decision_literal_enforcement():
    # Valid decision
    resp = InterceptionResponse(
        transaction_id="TX-OK",
        decision="HOLD",
        composite_risk=85.0,
        latency_ms=12.4,
        reasons=["Critical voice clone detected"],
        breakdown=RiskBreakdown(acoustic_score=90.0, graph_score=80.0, nlp_score=70.0, composite_risk=85.0)
    )
    assert resp.decision == "HOLD"

    # Invalid decision type rejected
    with pytest.raises(ValidationError):
        InterceptionResponse(
            transaction_id="TX-FAIL",
            decision="IGNORE_EVERYTHING",
            composite_risk=85.0,
            latency_ms=10.0,
            reasons=[],
            breakdown=RiskBreakdown(composite_risk=85.0)
        )

# ============================================================================
# 3. HTTP Endpoints & Integration Tests
# ============================================================================

def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["service"] == "trinetra-middleware"
    assert "timestamp" in data

def test_cors_headers_present(client):
    res = client.options("/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert res.status_code == 200
    assert "access-control-allow-origin" in res.headers

def test_validate_schema_endpoint_success(client):
    payload = {
        "transaction_id": "TX-VERIFY-88",
        "sender_account": "USER-44",
        "recipient_account": "MULE-88",
        "amount": 75000.0,
        "channel": "IMPS",
        "narrative_context": "urgent wire",
        "recipient_account_age_days": 12
    }
    res = client.post("/api/v1/intercept", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["transaction_id"] == "TX-VERIFY-88"
    assert body["decision"] in ["ALLOW", "STEP_UP", "HOLD"]
    assert "breakdown" in body
    assert body["latency_ms"] < MAX_INTERCEPT_LATENCY_MS

def test_validate_schema_endpoint_422_on_missing_fields(client):
    # Missing required amount and recipient
    bad_payload = {
        "transaction_id": "TX-BAD-01"
    }
    res = client.post("/api/v1/intercept", json=bad_payload)
    assert res.status_code == 422
