from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal

DecisionType = Literal["ALLOW", "STEP_UP", "HOLD"]
PaymentChannel = Literal["UPI", "IMPS", "WIRE", "NEFT", "RTGS", "CARD"]

class TransactionPayload(BaseModel):
    transaction_id: str = Field(..., min_length=1, description="Unique transaction reference ID")
    sender_account: str = Field(..., min_length=1, description="Originating account ID")
    recipient_account: str = Field(..., min_length=1, description="Destination account ID")
    amount: float = Field(..., gt=0, description="Transaction monetary amount")
    channel: PaymentChannel = Field(default="UPI", description="Payment rail (UPI, IMPS, WIRE, NEFT, RTGS, CARD)")
    timestamp: Optional[str] = None
    narrative_context: Optional[str] = Field(default=None, description="Transfer remark or extortion text transcript")
    audio_base64: Optional[str] = Field(default=None, description="Base64-encoded WAV authorization call audio")
    recipient_account_age_days: int = Field(default=365, ge=0, description="Age of recipient account in days")

class AcousticDiagnostics(BaseModel):
    is_synthetic: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    spectral_flatness: float = 0.0
    spectral_entropy: float = 0.0
    spectral_rolloff: float = 0.0
    high_freq_ratio: float = 0.0

class GraphDiagnostics(BaseModel):
    is_mule_ring: bool = False
    hop_count: int = Field(1, ge=1)
    dispersion_velocity: float = Field(0.0, ge=0.0)
    cycle_detected: bool = False
    quarantined_nodes: List[str] = []

class RiskBreakdown(BaseModel):
    acoustic_score: float = Field(0.0, ge=0.0, le=100.0)
    graph_score: float = Field(0.0, ge=0.0, le=100.0)
    nlp_score: float = Field(0.0, ge=0.0, le=100.0)
    composite_risk: float = Field(0.0, ge=0.0, le=100.0)

class InterceptionResponse(BaseModel):
    transaction_id: str = Field(..., min_length=1)
    decision: DecisionType = Field(..., description="ALLOW | STEP_UP | HOLD")
    composite_risk: float = Field(..., ge=0.0, le=100.0)
    latency_ms: float = Field(..., ge=0.0)
    reasons: List[str]
    breakdown: RiskBreakdown
    acoustic_diagnostics: Optional[AcousticDiagnostics] = None
    graph_diagnostics: Optional[GraphDiagnostics] = None

class SOCEvent(BaseModel):
    event_type: str = "TRANSACTION_EVALUATED"
    timestamp: str
    data: Dict[str, Any]

