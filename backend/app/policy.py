"""Versioned deterministic risk policy.

Inputs are the four signal categories from the architecture (voice authenticity,
spoken content, typed remark, recipient graph) plus restrictions and amount. Each
category is always present in the decision snapshot, even when unavailable.

Eligibility:
  * Restrictions -> BLOCK.
  * HOLD needs eligible evidence: an enforced (validated) model flag, or deterministic
    graph fan-in combined with a deterministic coercion-rule hit. Review-only model
    scores and inconclusive voice never cause a hold.
  * STEP_UP when screening evidence is insufficient or any single concern is present.
"""
from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = "2026.11-r2"

LOW_VALUE_MINOR = 5_000_00          # ₹5,000
NEW_RECIPIENT_STEP_UP_MINOR = 10_000_00  # ₹10,000
HIGH_VALUE_MINOR = 2_00_000_00      # ₹2,00,000

SIGNALS = ("voice_authenticity", "speech_content", "typed_remark", "recipient_graph")


@dataclass
class Decision:
    decision: str
    reasons: list[dict] = field(default_factory=list)
    policy_version: str = POLICY_VERSION
    signal_status: dict = field(default_factory=dict)


def _r(code: str, text: str, effect: str, signal: str | None = None) -> dict:
    return {"code": code, "text": text, "effect": effect, "signal": signal}


def suspicion_level(decision: str, reasons: list[dict]) -> str:
    if decision in ("HOLD", "BLOCK"):
        return "high"
    codes = {reason["code"] for reason in reasons}
    if codes & {"coercion_rules", "fan_in"} or any(code.endswith("_review_flag") for code in codes):
        return "elevated"
    if codes & {"insufficient_evidence", "voice_inconclusive", "unsupported_language", "remark_unscreened"}:
        return "inconclusive"
    return "low"


def evaluate(*, amount_minor: int, restricted: list[dict], signals: dict[str, dict],
             direction: str = "outgoing") -> Decision:
    for s in SIGNALS:
        signals.setdefault(s, {"signal": s, "status": "unavailable", "review_only": True, "reason": "not produced"})
    status = {k: {"status": v.get("status"), "review_only": bool(v.get("review_only", True)),
                  "flagged": v.get("flagged")} for k, v in signals.items()}

    if restricted:
        return Decision("BLOCK", [_r("restricted", f"Active restriction on {r['scope_type']}", "BLOCK") for r in restricted],
                        signal_status=status)

    reasons: list[dict] = []
    hold = False
    step = False

    g = signals["recipient_graph"]
    speech = signals["speech_content"]
    remark = signals["typed_remark"]
    voice = signals["voice_authenticity"]

    rule_hit = any((s.get("rules") or {}).get("flagged") for s in (speech, remark))
    rule_cats = sorted({c for s in (speech, remark) for c in ((s.get("rules") or {}).get("hits") or {})})

    # Enforced (validated) model flags may hold; review-only flags step up.
    for name in ("voice_authenticity", "speech_content", "typed_remark"):
        s = signals[name]
        if s.get("flagged") and s.get("status") == "flagged":
            if not s.get("review_only", True):
                hold = True
                reasons.append(_r(f"{name}_model_flag", f"Validated {name.replace('_', ' ')} model flagged this transfer", "HOLD", name))
            else:
                step = True
                reasons.append(_r(f"{name}_review_flag", f"Review-only {name.replace('_', ' ')} score above threshold", "STEP_UP", name))

    if g.get("flagged") and rule_hit:
        hold = True
        reasons.append(_r("fan_in_with_coercion", "Recipient shows multi-customer fan-in and the call or remark matched coercion rules", "HOLD", "recipient_graph"))
    elif g.get("flagged"):
        step = True
        reasons.append(_r("fan_in", "; ".join(g.get("reasons", [])[:1]) or "Recipient fan-in", "STEP_UP", "recipient_graph"))
    if rule_hit:
        step = True
        reasons.append(_r("coercion_rules", "Call or remark matched coercion patterns: " + ", ".join(c.replace("_", " ") for c in rule_cats), "STEP_UP"))

    new_rel = bool(g.get("new_relationship", True))
    if new_rel and amount_minor >= NEW_RECIPIENT_STEP_UP_MINOR:
        step = True
        relation = "from this sender" if direction == "incoming" else "to this recipient"
        reasons.append(_r("new_recipient_amount", f"First transfer {relation} at or above ₹10,000", "STEP_UP", "recipient_graph"))
    if amount_minor >= HIGH_VALUE_MINOR:
        step = True
        reasons.append(_r("high_value", "Amount at or above ₹2,00,000", "STEP_UP"))

    speech_ok = speech.get("status") in ("ok", "flagged") and speech.get("model_id") is not None
    if speech.get("status") == "unsupported_language":
        reasons.append(_r("unsupported_language", "Transcript language not supported by the screening model", "STEP_UP", "speech_content"))
    if not speech_ok:
        established_small = direction == "outgoing" and (not new_rel) and amount_minor <= LOW_VALUE_MINOR
        if established_small:
            reasons.append(_r("speech_unscreened_low_value", "Spoken content not screened; established relationship and low value accepted", "NOTE", "speech_content"))
        else:
            step = True
            reasons.append(_r("insufficient_evidence", "Spoken content could not be screened, so additional verification is required", "STEP_UP", "speech_content"))
    if voice.get("status") not in ("ok", "flagged") or voice.get("model_id") is None:
        effect = "STEP_UP" if direction == "incoming" else "NOTE"
        reasons.append(_r("voice_inconclusive", "Voice authenticity could not be determined", effect, "voice_authenticity"))
        step = step or direction == "incoming"
    if direction == "incoming" and remark.get("status") in ("unsupported_language", "unavailable", "inconclusive"):
        reasons.append(_r("remark_unscreened", "The typed remark could not be screened", "STEP_UP", "typed_remark"))
        step = True
    if g.get("truncated"):
        reasons.append(_r("graph_truncated", "Recipient graph search reached its bound", "NOTE", "recipient_graph"))

    decision = "HOLD" if hold else "STEP_UP" if step else "ALLOW"
    if decision == "ALLOW":
        reasons.append(_r("allow", "No restriction or concern found in eligible evidence", "ALLOW"))
    return Decision(decision, reasons, signal_status=status)
