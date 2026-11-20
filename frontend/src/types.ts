// All types mirror the backend Pydantic schemas exactly.

export type Decision = 'ALLOW' | 'STEP_UP' | 'HOLD';
export type Channel = 'UPI' | 'IMPS' | 'WIRE' | 'NEFT' | 'RTGS' | 'CARD';

export interface TransactionPayload {
  transaction_id?: string;
  sender_account: string;
  recipient_account: string;
  amount: number;
  channel: Channel;
  recipient_account_age_days?: number;
  narrative_context?: string;
  audio_base64?: string | null;
}

export interface AcousticDiagnostics {
  is_synthetic: boolean;
  confidence: number;
  spectral_flatness: number;
  spectral_entropy: number;
  spectral_rolloff: number;
  high_freq_ratio: number;
}

export interface GraphDiagnostics {
  is_mule_ring: boolean;
  hop_count: number;
  dispersion_velocity: number;
  velocity?: number;
  cycle_detected: boolean;
  quarantined_nodes: string[];
}

export interface RiskBreakdown {
  acoustic_score: number;
  graph_score: number;
  nlp_score: number;
  composite_risk: number;
}

export interface InterceptionResponse {
  transaction_id: string;
  decision: Decision;
  composite_risk: number;
  latency_ms: number;
  reasons: string[];
  breakdown: RiskBreakdown;
  acoustic_diagnostics: AcousticDiagnostics;
  graph_diagnostics: GraphDiagnostics;
}

export interface CytoscapeNode {
  data: {
    id: string;
    label: string;
    type?: 'standard' | 'new_account' | 'quarantined' | string;
    age_days?: number;
    total_in?: number;
    total_out?: number;
  };
}

export interface CytoscapeEdge {
  data: {
    id: string;
    source: string;
    target: string;
    amount?: number;
    tx_id?: string;
    label?: string;
  };
}

export interface CytoscapeGraph {
  nodes: CytoscapeNode[];
  edges: CytoscapeEdge[];
  elements?: {
    nodes?: CytoscapeNode[];
    edges?: CytoscapeEdge[];
  };
}

// WebSocket event types
export interface SOCEvent {
  event_type: 'TRANSACTION_EVALUATED' | 'ANALYST_OVERRIDE' | 'CONNECTED';
  timestamp: string;
  transaction?: TransactionPayload;
  transaction_id?: string;
  channel?: Channel;
  amount?: number;
  decision?: Decision;
  composite_risk?: number;
  latency_ms?: number;
  reasons?: string[];
  breakdown?: RiskBreakdown;
  risk_breakdown?: RiskBreakdown;
  acoustic_diagnostics?: AcousticDiagnostics;
  graph_diagnostics?: GraphDiagnostics;
  cytoscape_subgraph?: CytoscapeGraph;
  // Analyst override fields
  account?: string;
  account_id?: string;
  action?: string;
  analyst_id?: string;
  note?: string;
  status_message?: string;
  // Connected fields
  message?: string;
  quarantined_count?: number;
}

export interface ScenarioMeta {
  id: string;
  title: string;
  name?: string;
  description: string;
  expected_decision: Decision;
  expected_risk_range: [number, number];
  channel: Channel;
  amount: number;
}

export interface Metrics {
  total_evaluated: number;
  allowed: number;
  stepped_up: number;
  held: number;
  average_latency_ms: number;
  quarantined_accounts_count: number;
}
