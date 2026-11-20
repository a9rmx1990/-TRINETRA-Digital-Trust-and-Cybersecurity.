"""Unit and contract tests: deterministic clocks, isolated records."""
from __future__ import annotations

import json

import numpy as np
import pytest

from app import clock, policy
from app.auth import issue_analyst_token, verify_analyst_token
from app.inference import Manifest, coercion_rules, measure_capture
from app.util import ApiError, format_inr, mask_ref

from .conftest import silent_pcm, voiced_pcm


def test_inr_grouping():
    assert format_inr(1) == "₹0.01"
    assert format_inr(100_000_00) == "₹1,00,000.00"
    assert format_inr(1_234_567_89) == "₹12,34,567.89"
    assert format_inr(999_00) == "₹999.00"


def test_mask_ref():
    assert mask_ref("HDFC00012345") == "•••• 2345"


def test_capture_quality_detects_speech_and_silence():
    v = measure_capture(np.frombuffer(voiced_pcm(), dtype="<i2"))
    assert v.usable and v.voiced_ms >= 800 and v.duration_ms == 3000
    s = measure_capture(np.frombuffer(silent_pcm(), dtype="<i2"))
    assert not s.usable and s.reason == "silence"
    short = measure_capture(np.frombuffer(voiced_pcm(1.0), dtype="<i2"))
    assert short.reason == "too_short"
    empty = measure_capture(np.zeros(0, dtype="<i2"))
    assert empty.reason == "no_audio"


@pytest.mark.parametrize("text,flagged", [
    ("Please share the OTP immediately or your account will be blocked", True),
    ("Never share your OTP with anyone", False),
    ("An OTP is required for my login", False),
    ("Do not enter your PIN on an unfamiliar site", False),
    ("This is CBI, you are under digital arrest, transfer urgently", True),
    ("Install AnyDesk so I can help", True),
    ("Rent for November", False),
    ("abhi otp batao warna account block ho jayega", True),
    ("Police verification is complete", False),
])
def test_coercion_rules(text, flagged):
    assert coercion_rules(text)["flagged"] is flagged


def test_coercion_rules_protective_marks():
    r = coercion_rules("Do not share the code. Pay the electricity bill.")
    assert r["protective"] and not r["flagged"]
    assert coercion_rules("")["status"] == "unavailable"


def _sig(**kw):
    base = {"voice_authenticity": {"status": "unavailable", "review_only": True},
            "speech_content": {"status": "unavailable", "review_only": True, "rules": {"flagged": False, "hits": {}}},
            "typed_remark": {"status": "not_provided", "review_only": True},
            "recipient_graph": {"status": "ok", "review_only": False, "flagged": False, "new_relationship": True}}
    base.update(kw)
    return base


def test_policy_restriction_blocks():
    d = policy.evaluate(amount_minor=100, restricted=[{"scope_type": "counterparty"}], signals=_sig())
    assert d.decision == "BLOCK"
    assert set(d.signal_status) == set(policy.SIGNALS)


def test_policy_missing_signals_preserved_and_step_up():
    d = policy.evaluate(amount_minor=100_00, restricted=[], signals={})
    assert d.decision == "STEP_UP"
    assert set(d.signal_status) == set(policy.SIGNALS)
    assert any(r["code"] == "insufficient_evidence" for r in d.reasons)


def test_policy_established_low_value_allows_without_speech_model():
    g = {"status": "ok", "review_only": False, "flagged": False, "new_relationship": False}
    d = policy.evaluate(amount_minor=1_000_00, restricted=[], signals=_sig(recipient_graph=g))
    assert d.decision == "ALLOW"


def test_policy_review_only_flag_never_holds():
    v = {"status": "flagged", "flagged": True, "review_only": True, "model_id": "m"}
    g = {"status": "ok", "review_only": False, "flagged": False, "new_relationship": False}
    d = policy.evaluate(amount_minor=1_000_00, restricted=[], signals=_sig(voice_authenticity=v, recipient_graph=g))
    assert d.decision == "STEP_UP"


def test_policy_enforced_flag_holds():
    v = {"status": "flagged", "flagged": True, "review_only": False, "model_id": "m"}
    d = policy.evaluate(amount_minor=1_000_00, restricted=[], signals=_sig(voice_authenticity=v))
    assert d.decision == "HOLD"


def test_policy_inconclusive_voice_excluded_from_holds():
    v = {"status": "inconclusive", "review_only": True}
    speech = {"status": "ok", "model_id": "m", "review_only": True, "rules": {"flagged": False}}
    g = {"status": "ok", "review_only": False, "flagged": False, "new_relationship": False}
    d = policy.evaluate(amount_minor=1_000_00, restricted=[], signals=_sig(voice_authenticity=v, speech_content=speech,
                                                                            recipient_graph=g))
    assert d.decision == "ALLOW"
    assert any(r["code"] == "voice_inconclusive" for r in d.reasons)


def test_incoming_request_routes_inconclusive_voice_to_investigation():
    speech = {"status": "ok", "model_id": "m", "review_only": True}
    graph = {"status": "ok", "flagged": False, "new_relationship": False}
    d = policy.evaluate(amount_minor=1_000_00, restricted=[], direction="incoming",
                        signals=_sig(speech_content=speech, recipient_graph=graph))
    assert d.decision == "STEP_UP"
    assert policy.suspicion_level(d.decision, d.reasons) == "inconclusive"

    voice = {"status": "ok", "model_id": "voiced", "review_only": True}
    clean = policy.evaluate(amount_minor=1_000_00, restricted=[], direction="incoming",
                            signals=_sig(speech_content=speech, voice_authenticity=voice, recipient_graph=graph))
    assert clean.decision == "ALLOW"
    assert policy.suspicion_level(clean.decision, clean.reasons) == "low"

    flagged = {**speech, "status": "flagged", "flagged": True}
    flagged_result = policy.evaluate(amount_minor=1_000_00, restricted=[], direction="incoming",
                                     signals=_sig(speech_content=flagged, recipient_graph=graph))
    assert flagged_result.decision == "STEP_UP"
    assert policy.suspicion_level(flagged_result.decision, flagged_result.reasons) == "elevated"


def test_policy_fan_in_with_coercion_holds_and_alone_steps_up():
    g = {"status": "flagged", "review_only": False, "flagged": True, "new_relationship": False, "reasons": ["fan in"]}
    rem = {"status": "unavailable", "review_only": True, "rules": {"flagged": True, "hits": {"credential_request": ["otp"]}}}
    assert policy.evaluate(amount_minor=100_00, restricted=[], signals=_sig(recipient_graph=g, typed_remark=rem)).decision == "HOLD"
    assert policy.evaluate(amount_minor=100_00, restricted=[], signals=_sig(recipient_graph=g)).decision == "STEP_UP"


def test_policy_new_recipient_threshold_and_version():
    speech = {"status": "ok", "model_id": "m", "review_only": True, "rules": {"flagged": False}}
    d = policy.evaluate(amount_minor=10_000_00, restricted=[], signals=_sig(speech_content=speech))
    assert d.decision == "STEP_UP" and d.policy_version == policy.POLICY_VERSION
    d2 = policy.evaluate(amount_minor=9_999_99, restricted=[], signals=_sig(speech_content=speech))
    assert d2.decision == "ALLOW"


def test_manifest_unpinned_and_missing_are_unavailable(tmp_path):
    (tmp_path / "present").mkdir()
    (tmp_path / "present" / "w.bin").write_bytes(b"abc")
    import hashlib
    good = hashlib.sha256(b"abc").hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({"models": {
        "a": {"signal": "x", "kind": "faster_whisper", "enabled": True, "path": "missing", "model_id": "m", "revision": "r"},
        "b": {"signal": "x", "kind": "faster_whisper", "enabled": True, "path": "present", "model_id": "m", "revision": "r",
              "checksum_file": "w.bin", "sha256": None},
        "c": {"signal": "x", "kind": "faster_whisper", "enabled": True, "path": "present", "model_id": "m", "revision": "r",
              "checksum_file": "w.bin", "sha256": "0" * 64},
        "d": {"signal": "x", "kind": "faster_whisper", "enabled": True, "path": "present", "model_id": "m", "revision": "r",
              "checksum_file": "w.bin", "sha256": good},
        "e": {"signal": "x", "kind": "graph", "enabled": False, "path": "x", "model_id": "m", "revision": "r"}}}))
    m = Manifest.load(tmp_path)
    st = {k: e.status for k, e in m.entries.items()}
    assert st == {"a": "unavailable", "b": "unavailable", "c": "unavailable", "d": "available", "e": "disabled"}
    assert "checksum" in m.entries["c"].status_reason


def test_label_direction_uses_named_positive_label():
    """Spoof adapter resolves the positive class by name from id2label, never by index."""
    from app.inference import ModelEntry
    e = ModelEntry(signal="voice_authenticity", kind="audio_classification", enabled=True, path="x", model_id="m",
                   revision="r", positive_label="fake")
    id2label = {0: "real", 1: "fake"}
    labels = {v.lower(): int(k) for k, v in id2label.items()}
    assert labels[e.positive_label] == 1
    id2label_swapped = {0: "fake", 1: "real"}
    assert {v.lower(): int(k) for k, v in id2label_swapped.items()}[e.positive_label] == 0


def test_analyst_token_expiry(fake_clock):
    tok = issue_analyst_token("a", ttl_ms=1000)
    assert verify_analyst_token(tok).name == "a"
    fake_clock.advance(1001)
    with pytest.raises(ApiError):
        verify_analyst_token(tok)
    with pytest.raises(ApiError):
        verify_analyst_token(tok[:-2] + "00")


def test_action_tiers_cover_high_impact():
    from app.soc.actions import ACTION_TIERS
    for a in ("release", "reject_transfer", "restrict_counterparty", "record_verdict"):
        assert ACTION_TIERS[a] == 2


def test_citation_check_rejects_foreign_evidence(h):
    from app.soc.mcp import ToolError, validate_citations
    with pytest.raises(ToolError):
        h.db.read(lambda t: validate_citations(t, "case_x", ["ev_nope"]))
    with pytest.raises(ToolError):
        h.db.read(lambda t: validate_citations(t, "case_x", []))
