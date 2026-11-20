"""Policy & Risk Decisioning Engine: Unified Multi-Signal Risk Aggregator.

Computes weighted composite risk R(T) across acoustic, graph, and NLP forensic signals,
enforcing sub-150ms dynamic friction (ALLOW, STEP_UP, HOLD) and emergency overrides.
"""

from typing import List, Tuple
from app.config import (
    THRESHOLD_ALLOW_MAX,
    THRESHOLD_STEP_UP_MAX,
    WEIGHT_ACOUSTIC,
    WEIGHT_GRAPH,
    WEIGHT_NLP
)
from app.schemas import DecisionType, RiskBreakdown

class PolicyDecisionEngine:
    def __init__(
        self,
        weight_acoustic: float = WEIGHT_ACOUSTIC,
        weight_graph: float = WEIGHT_GRAPH,
        weight_nlp: float = WEIGHT_NLP,
        allow_max: float = THRESHOLD_ALLOW_MAX,
        step_up_max: float = THRESHOLD_STEP_UP_MAX
    ):
        self.w_audio = weight_acoustic
        self.w_graph = weight_graph
        self.w_nlp = weight_nlp
        self.allow_max = allow_max
        self.step_up_max = step_up_max

    def evaluate(
        self,
        acoustic_score: float,
        graph_score: float,
        nlp_score: float,
        reasons_audio: List[str],
        reasons_graph: List[str],
        reasons_nlp: List[str],
        is_quarantined: bool = False
    ) -> Tuple[DecisionType, float, List[str], RiskBreakdown]:
        """Calculates composite risk score and outputs deterministic action policy."""
        consolidated_reasons: List[str] = []

        # 1. Absolute Quarantine Veto
        if is_quarantined:
            composite_risk = 100.0
            decision: DecisionType = "HOLD"
            consolidated_reasons.append("CRITICAL: Counterparty account is permanently quarantined in the AML fraud registry.")
            consolidated_reasons.extend(reasons_graph)
            breakdown = RiskBreakdown(
                acoustic_score=acoustic_score,
                graph_score=100.0,
                nlp_score=nlp_score,
                composite_risk=100.0
            )
            return decision, composite_risk, consolidated_reasons, breakdown

        # 2. Dynamic Weight Aggregation
        # If audio stream is not present in transaction, renormalize weights across active signals
        has_audio = not any("no audio" in r.lower() for r in reasons_audio) and len(reasons_audio) > 0
        if not has_audio and (self.w_graph + self.w_nlp) > 0:
            norm_factor = 1.0 / (self.w_graph + self.w_nlp)
            raw_composite = (self.w_graph * norm_factor * graph_score) + (self.w_nlp * norm_factor * nlp_score)
        else:
            raw_composite = (
                self.w_audio * acoustic_score +
                self.w_graph * graph_score +
                self.w_nlp * nlp_score
            )
        composite_risk = round(min(100.0, max(0.0, raw_composite)), 1)

        # 3. Single-Vector Extreme Threat Overrides
        critical_override = False
        if acoustic_score >= 85.0:
            critical_override = True
            composite_risk = max(composite_risk, 75.0)
            consolidated_reasons.append("HIGH-PRIORITY OVERRIDE: Forensic voice clone verified in out-of-band call.")
        elif acoustic_score >= 50.0:
            composite_risk = max(composite_risk, 45.0)
            consolidated_reasons.append("HIGH-PRIORITY WARNING: Anomalous acoustic harmonics detected. Step-up required.")
        elif has_audio and acoustic_score <= 15.0:
            consolidated_reasons.append("Acoustic authorization verified: Human biological vocal tract dynamics confirmed.")
        
        if graph_score >= 85.0:
            critical_override = True
            composite_risk = max(composite_risk, 78.0)
            consolidated_reasons.append("HIGH-PRIORITY OVERRIDE: Active multi-hop money-mule laundering network confirmed.")

        if nlp_score >= 80.0:
            if graph_score >= 20.0:
                critical_override = True
                composite_risk = max(composite_risk, 78.0)
                consolidated_reasons.append("HIGH-PRIORITY OVERRIDE: Severe coercive extortion (Digital Arrest) targeting high-risk destination account.")
            else:
                composite_risk = max(composite_risk, 55.0)
                consolidated_reasons.append("HIGH-PRIORITY WARNING: Coercive extortion script detected.")

        # 4. Gating Threshold Decision
        if composite_risk >= self.step_up_max or critical_override:
            decision = "HOLD"
            consolidated_reasons.append(f"Transaction frozen (Composite Risk {composite_risk} >= {self.step_up_max}). SOC queue updated.")
        elif composite_risk >= self.allow_max:
            decision = "STEP_UP"
            consolidated_reasons.append(f"Dynamic friction injected (Composite Risk {composite_risk} between {self.allow_max} and {self.step_up_max}). Step-up biometric challenge dispatched.")
        else:
            decision = "ALLOW"
            consolidated_reasons.append(f"Risk within permissible baseline (Composite Risk {composite_risk} < {self.allow_max}). Fast-path cleared.")

        # Append specific engine explanations (skipping default boilerplate if elevated)
        for r in reasons_audio:
            if "no audio" not in r.lower() and "biological vocal" not in r.lower():
                consolidated_reasons.append(f"[Acoustic] {r}")

        for r in reasons_graph:
            if "normal low-degree" not in r.lower():
                consolidated_reasons.append(f"[Graph] {r}")

        for r in reasons_nlp:
            if "no narrative" not in r.lower() and "standard non-coercive" not in r.lower():
                consolidated_reasons.append(f"[Context] {r}")

        breakdown = RiskBreakdown(
            acoustic_score=acoustic_score,
            graph_score=graph_score,
            nlp_score=nlp_score,
            composite_risk=composite_risk
        )

        return decision, composite_risk, consolidated_reasons, breakdown
