import type { CytoscapeGraph } from './types';

const base = import.meta.env.VITE_API_URL ?? '';

export type Payment = {
  payment_id: string; recipient: string; amount_minor: number; currency: string;
  state: 'SETTLED' | 'STEP_UP_REQUIRED' | 'HELD' | 'BLOCKED'; decision: 'ALLOW' | 'STEP_UP' | 'HOLD' | 'BLOCK';
};

type ModelSignal = { status: string; version?: string; score?: number };
type WindowEvidence = {
  baseline: { score: number; spectrum_db: number[] };
  spoof: ModelSignal; asr: ModelSignal & { text?: string; language?: string };
  evidence_id: string; end_ms: number;
};
export type InvestigationHistory = {
  lookback_days: number;
  session_payments: number; session_flagged: number;
  recipient_payments: number; recipient_flagged: number;
  other_session_recipient_flagged: number;
  related_cases: { payment_id: string; created: number; state: Payment['state']; same_session: number; same_recipient: number }[];
};

type AgentVerdict = {
  verdict: 'fraud' | 'suspicious' | 'benign'; confidence: number; rationale: string;
  evidence_ids: string[]; recommended_action: string;
};
type AgentCase = {
  max_tier: number; kill_switch: boolean; hold_until: number | null;
  watch: { status: string; next_at: number; through_at: number } | null;
  feedback: { verdict: AgentVerdict['verdict']; rationale: string } | null;
  timeline: { seq: number; role: string; tool: string; outcome: string; created_at: number }[];
  proposals: { id: string; case_version: number; action: string; status: string; note: string | null }[];
};
export type Triage = {
  investigated_at?: number;
  verdict?: AgentVerdict;
  provider_status?: string;
  history?: InvestigationHistory;
  summary: string; source: string; recommendation: string;
  references: { window: string | null; path: string[]; transcript_window?: string | null };
};
export type Case = Payment & {
  triage: Triage;
  agent?: AgentCase;
  voice_verdict?: 'likely_genuine' | 'suspected_synthetic' | 'inconclusive';
  version: number; risk_score: number; policy_version: string; case_status: string; reasons: string[];
  evidence_id: string | null;
  evidence: {
    graph: CytoscapeGraph & { score: number; path: string[]; cycle: string[]; truncated: boolean };
    gnn: ModelSignal; fusion: ModelSignal;
    call: { transport: string; acoustic: WindowEvidence; coercion: WindowEvidence } | null;
  };
  events?: { seq: number; kind: string; actor: string; time: number; detail: { note?: string } }[];
};
export type SocOverview = {
  payments: number; sessions: number; flagged: number; open: number; investigated: number; ai_assessed: number;
  daily: { day: number; payments: number; flagged: number }[];
};
export type CasePage = { cursor: number; updated_ids: string[]; overview: SocOverview; cases: Array<Pick<Case, "payment_id" | "recipient" | "amount_minor" | "state" | "case_status" | "risk_score">>; recent: (Payment & { has_case: boolean })[] };
export type SandboxConfig = { recipients: string[]; configured_models: string[]; analyst_enabled: boolean };

export function customerKey() {
  const previous = sessionStorage.getItem('trinetra-caller');
  if (previous) return previous;
  const key = Array.from(crypto.getRandomValues(new Uint8Array(32)), byte =>
    byte.toString(16).padStart(2, '0')).join('');
  sessionStorage.setItem('trinetra-caller', key);
  return key;
}

export async function api<T>(path: string, key?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (key) headers.set('Authorization', 'Bearer ' + key);
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json');
  const response = await fetch(base + '/api/v2' + path, {
    ...init, headers, signal: init.signal ?? AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail :
      response.status === 422 ? 'Check the values entered and try again.' : 'Request failed (' + response.status + ').');
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function post(body?: unknown): RequestInit {
  return { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) };
}

export function caseSocket() {
  const url = new URL(base + '/api/v2/case-stream', location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return new WebSocket(url);
}

export function money(amount: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' }).format(amount / 100);
}
