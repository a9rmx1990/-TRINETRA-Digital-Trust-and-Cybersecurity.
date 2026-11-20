"""Coercive Context & NLP Engine: Extortion and Psychological Coercion Detection.

Detects legal/authority impersonation (CBI, Police, Digital Arrest),
bogus safe-escrow demands, and coercive urgency cues in narrative text or transcripts.
"""

import re
from typing import Tuple, List, Dict, Set

# Compiled regex patterns grouped by threat category
COERCION_TAXONOMY: Dict[str, List[re.Pattern]] = {
    "AUTHORITY_IMPERSONATION": [
        re.compile(r"\b(cbi|customs|interpol|cyber\s*police|federal\s*police|enforcement\s*directorate|ed|supreme\s*court)\b", re.IGNORECASE),
        re.compile(r"\b(digital\s*arrest|arrest\s*warrant|court\s*summons|non-bailable|fir\s*registered)\b", re.IGNORECASE),
        re.compile(r"\b(narcotics|money\s*laundering\s*case|trafficking\s*probe|national\s*security\s*act)\b", re.IGNORECASE),
    ],
    "FRAUDULENT_ROUTING": [
        re.compile(r"\b(safe\s*(state\s*)?escrow|safe\s*government\s*account|verification\s*account|reserve\s*account)\b", re.IGNORECASE),
        re.compile(r"\b(clearing\s*wallet|rbi\s*holding\s*account|treasury\s*holding|refund\s*escrow)\b", re.IGNORECASE),
        re.compile(r"\b(asset\s*liquidation|penalty\s*deposit|bail\s*deposit|clearance\s*charge)\b", re.IGNORECASE),
    ],
    "COERCIVE_URGENCY": [
        re.compile(r"\b(do\s*not\s*(disconnect|hang\s*up)|remain\s*on\s*call|camera\s*must\s*remain\s*on)\b", re.IGNORECASE),
        re.compile(r"\b(immediate\s*(liquidation|arrest|seizure|transfer|action))\b", re.IGNORECASE),
        re.compile(r"\b(keep\s*this\s*confidential|do\s*not\s*tell\s*(anyone|family|bank))\b", re.IGNORECASE),
        re.compile(r"\b(within\s*(10|15|30)\s*minutes|under\s*surveillance)\b", re.IGNORECASE),
    ]
}

class CoerciveContextEngine:
    def __init__(self):
        pass

    def analyze(self, text: str | None) -> Tuple[float, List[str], Dict[str, List[str]]]:
        """Analyzes text context for psychological coercion markers.
        Returns: (nlp_score: float 0-100, reasons: list[str], matched_categories: dict)
        """
        if not text or not text.strip():
            return 0.0, ["No narrative context provided."], {}

        cleaned = text.strip()
        matched_categories: Dict[str, List[str]] = {}
        detected_categories: Set[str] = set()
        anomaly_points = 0.0
        reasons = []

        # 1. Authority / Legal Impersonation (Up to 45 pts)
        auth_matches = []
        for pat in COERCION_TAXONOMY["AUTHORITY_IMPERSONATION"]:
            m = pat.findall(cleaned)
            if m:
                flat = [item if isinstance(item, str) else item[0] for item in m]
                auth_matches.extend(flat)
        if auth_matches:
            detected_categories.add("AUTHORITY_IMPERSONATION")
            matched_categories["AUTHORITY_IMPERSONATION"] = list(set(auth_matches))
            anomaly_points += 45.0
            reasons.append(f"Authority impersonation cues detected: {', '.join(sorted(set(auth_matches))[:3])}.")

        # 2. Fraudulent Escrow / Safe Account Routing (Up to 35 pts)
        routing_matches = []
        for pat in COERCION_TAXONOMY["FRAUDULENT_ROUTING"]:
            m = pat.findall(cleaned)
            if m:
                flat = [item if isinstance(item, str) else item[0] for item in m]
                routing_matches.extend(flat)
        if routing_matches:
            detected_categories.add("FRAUDULENT_ROUTING")
            matched_categories["FRAUDULENT_ROUTING"] = list(set(routing_matches))
            anomaly_points += 35.0
            reasons.append(f"Fraudulent safe-escrow routing phrasing detected: {', '.join(sorted(set(routing_matches))[:3])}.")

        # 3. Urgency & Isolation Pressure (Up to 25 pts)
        urgency_matches = []
        for pat in COERCION_TAXONOMY["COERCIVE_URGENCY"]:
            m = pat.findall(cleaned)
            if m:
                flat = [item if isinstance(item, str) else item[0] for item in m]
                urgency_matches.extend(flat)
        if urgency_matches:
            detected_categories.add("COERCIVE_URGENCY")
            matched_categories["COERCIVE_URGENCY"] = list(set(urgency_matches))
            anomaly_points += 25.0
            reasons.append(f"Coercive urgency & isolation phrasing detected: {', '.join(sorted(set(urgency_matches))[:3])}.")

        # Multi-category synergy penalty (Classic Digital Arrest pattern combines authority + urgency + routing)
        if len(detected_categories) >= 2:
            anomaly_points += 15.0
            reasons.append("High-severity combination of authority impersonation and coercive pressure.")

        nlp_score = min(100.0, max(0.0, anomaly_points))

        if not reasons:
            reasons.append("Narrative context contains standard non-coercive payment terms.")

        return round(nlp_score, 1), reasons, matched_categories
