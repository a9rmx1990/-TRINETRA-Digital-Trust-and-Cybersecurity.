from dataclasses import replace

import pytest

from app import clock
from app.intelligence import RULES, cluster, evaluate, risk_band

NOW = 100 * clock.DAY
PAYMENT = {"amount_minor": 50_000_00, "created_ms": NOW, "direction": "outgoing",
           "account_id": "acct1", "counterparty_id": "cp1", "beneficiary_id": "ben1"}


def baseline(count=10):
    return [{"id": f"p{i}", "amount_minor": 2_000_00,
             "created_ms": NOW - (i + 2) * clock.DAY + 8 * clock.HOUR} for i in range(count)]


def score(history, payment=PAYMENT, **changes):
    facts = {"beneficiary_added_ms": NOW, "known_beneficiary": True, "flagged": False, "recent_outgoing": 0}
    recent = changes.pop("recent", {})
    return evaluate(payment, history, recent, **(facts | changes))


@pytest.mark.parametrize(("value", "band"), [(0, "LOW"), (24, "LOW"), (25, "MEDIUM"), (49, "MEDIUM"),
                                            (50, "HIGH"), (74, "HIGH"), (75, "CRITICAL"), (100, "CRITICAL")])
def test_risk_band_boundaries(value, band):
    assert risk_band(value, RULES) == band


def test_cold_start_uses_policy_thresholds_and_counts_frequency_once():
    result = score([], known_beneficiary=False, recent={5: 4, 30: 8}, flagged=True)
    assert result["baseline"]["average_minor"] is None
    assert result["baseline"]["p90_minor"] is None
    assert [(s["code"], s["points"]) for s in result["signals"]] == [
        ("new_beneficiary_high_value", 20), ("unusual_frequency", 15), ("previously_flagged_entity", 20)
    ]
    assert len(result["signals"][1]["evidence"]["windows"]) == 2
    assert (result["score"], result["band"], result["alert"]) == (55, "HIGH", True)


def test_sufficient_history_enables_amount_timing_and_surge():
    result = score(baseline(), recent_outgoing=5_000_00)
    assert result["baseline"]["average_minor"] == 2_000_00
    assert [s["code"] for s in result["signals"]] == ["unusually_large", "unusual_timing", "outgoing_surge"]
    assert result["score"] == 45 and not result["alert"]


def test_low_value_and_typical_timing_do_not_trigger():
    usual = PAYMENT | {"amount_minor": 2_000_00, "created_ms": NOW + 8 * clock.HOUR}
    assert score(baseline(), usual, recent={5: 3}, recent_outgoing=5_000_00)["signals"] == []


def test_incoming_uses_receiving_history_without_outgoing_signals():
    result = score(baseline(), PAYMENT | {"direction": "incoming"}, known_beneficiary=False, recent_outgoing=50_000_00)
    assert [s["code"] for s in result["signals"]] == ["unusually_large", "unusual_timing"]


def test_score_is_capped_when_weights_exceed_ceiling():
    result = score(baseline(), recent={5: 4}, flagged=True, recent_outgoing=5_000_00,
                   rules=replace(RULES, weights=(50,) * 6))
    assert (result["score"], result["band"]) == (100, "CRITICAL")


def test_aml_needs_repetition_and_distinct_senders():
    def rows(senders):
        return [{"payment_id": str(i), "sender_key": sender, "amount_minor": 100} for i, sender in enumerate(senders)]

    assert cluster(rows("abc")) is None
    assert cluster(rows("aabb")) is None
    evidence = cluster(rows("abca"))
    assert (evidence["sender_count"], evidence["transaction_count"], evidence["total_minor"]) == (3, 4, 400)
    assert [row["payment_id"] for row in evidence["transactions"]] == ["0", "1", "2", "3"]
