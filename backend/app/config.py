"""TRINETRA Backend Configuration & Decision Thresholds."""

# Dynamic Decision Thresholds (Composite Risk Score 0 - 100)
THRESHOLD_ALLOW_MAX = 35.0      # Scores < 35: ALLOW
THRESHOLD_STEP_UP_MAX = 70.0    # Scores 35 - 69.9: STEP_UP (Biometric / Challenge)
                                # Scores >= 70: HOLD (Automatic Interception)

# Forensic Engine Default Weights (Sum = 1.0)
WEIGHT_ACOUSTIC = 0.45          # Voice-clone / synthetic audio weight
WEIGHT_GRAPH = 0.40             # Mule-ring / velocity topology weight
WEIGHT_NLP = 0.15               # Coercive context / extortion script weight

# Latency Target
MAX_INTERCEPT_LATENCY_MS = 150.0
