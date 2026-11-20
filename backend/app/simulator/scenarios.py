"""Attack Scenario Simulator: Preset Feeds for Live Demonstration.

Generates realistic telemetry for the 4 canonical demonstration scenarios:
1. Legitimate Baseline (Low Risk)
2. CEO Voice Clone Wire Scam (Critical Audio Risk)
3. 5-Hop Rapid Mule Ring (Critical Graph Risk)
4. Digital Arrest Extortion (Critical NLP & Account Risk)
"""

import base64
from typing import Dict, Any, List
from app.engines.audio_engine import AudioForensicsEngine
from app.schemas import TransactionPayload

def build_scenario_payloads() -> Dict[str, Dict[str, Any]]:
    # Pre-render standard authentic and synthetic audio buffers
    auth_audio_b64 = base64.b64encode(AudioForensicsEngine.generate_authentic_sample(duration_sec=2.0)).decode("ascii")
    synth_audio_b64 = base64.b64encode(AudioForensicsEngine.generate_synthetic_sample(duration_sec=2.0)).decode("ascii")

    return {
        "SCENARIO_1_BASELINE": {
            "id": "SCENARIO_1_BASELINE",
            "title": "Clean Recurring Payment",
            "description": "Standard monthly vendor transfer between mature accounts with human voice authorization.",
            "expected_decision": "ALLOW",
            "expected_risk_range": [0.0, 30.0],
            "setup_actions": [],
            "payload": {
                "transaction_id": "TX-BASE-1001",
                "sender_account": "ACC-CORP-PRIMARY",
                "recipient_account": "ACC-SUPPLIER-STEADY",
                "amount": 25000.0,
                "channel": "IMPS",
                "recipient_account_age_days": 420,
                "narrative_context": "Monthly supplies invoice settlement #INV-9921",
                "audio_base64": auth_audio_b64
            }
        },
        "SCENARIO_2_VOICE_CLONE": {
            "id": "SCENARIO_2_VOICE_CLONE",
            "title": "CEO Voice Clone Wire Scam",
            "description": "Urgent high-value wire authorization call using a zero-shot neural vocoder cloned voice.",
            "expected_decision": "HOLD",
            "expected_risk_range": [75.0, 100.0],
            "setup_actions": [],
            "payload": {
                "transaction_id": "TX-CLONE-2002",
                "sender_account": "ACC-FINANCE-DESK",
                "recipient_account": "ACC-OFFSHORE-ESCROW",
                "amount": 850000.0,
                "channel": "WIRE",
                "recipient_account_age_days": 18,
                "narrative_context": "Urgent executive wire order as instructed on authorization phone call.",
                "audio_base64": synth_audio_b64
            }
        },
        "SCENARIO_3_MULE_RING": {
            "id": "SCENARIO_3_MULE_RING",
            "title": "5-Hop Rapid Mule Ring",
            "description": "Stolen funds routed to a newly opened shell account that immediately fans out across 5 hops in 45s.",
            "expected_decision": "HOLD",
            "expected_risk_range": [78.0, 100.0],
            "setup_actions": [
                {"sender": "MULE-NODE-1", "recipient": "MULE-NODE-2", "amount": 480000.0, "age_days": 4},
                {"sender": "MULE-NODE-2", "recipient": "MULE-NODE-3", "amount": 460000.0, "age_days": 3},
                {"sender": "MULE-NODE-3", "recipient": "MULE-NODE-4", "amount": 440000.0, "age_days": 2},
                {"sender": "MULE-NODE-4", "recipient": "MULE-NODE-5", "amount": 420000.0, "age_days": 1},
            ],
            "payload": {
                "transaction_id": "TX-MULE-3003",
                "sender_account": "ACC-VICTIM-RETAIL",
                "recipient_account": "MULE-NODE-1",
                "amount": 500000.0,
                "channel": "UPI",
                "recipient_account_age_days": 4,
                "narrative_context": "urgent payment clearance",
                "audio_base64": None
            }
        },
        "SCENARIO_4_DIGITAL_ARREST": {
            "id": "SCENARIO_4_DIGITAL_ARREST",
            "title": "Digital Arrest Coercive Extortion",
            "description": "Senior citizen coerced into liquidating savings by scammers posing as CBI/Police demanding transfer to 'Safe Escrow'.",
            "expected_decision": "HOLD",
            "expected_risk_range": [70.0, 100.0],
            "setup_actions": [],
            "payload": {
                "transaction_id": "TX-ARREST-4004",
                "sender_account": "ACC-SENIOR-CITIZEN",
                "recipient_account": "MULE-ESCROW-COLLECTOR",
                "amount": 620000.0,
                "channel": "RTGS",
                "recipient_account_age_days": 8,
                "narrative_context": "CBI Cyber Police Digital Arrest notice: Non-bailable warrant. Transfer savings to Safe Government Escrow Verification Account. Do not disconnect call.",
                "audio_base64": None
            }
        }
    }

# Cache initialized scenario dictionary
_SCENARIO_CACHE: Dict[str, Dict[str, Any]] = {}

def get_scenarios() -> Dict[str, Dict[str, Any]]:
    global _SCENARIO_CACHE
    if not _SCENARIO_CACHE:
        _SCENARIO_CACHE = build_scenario_payloads()
    return _SCENARIO_CACHE

def get_scenario_by_id(scenario_id: str) -> Dict[str, Any] | None:
    return get_scenarios().get(scenario_id)
