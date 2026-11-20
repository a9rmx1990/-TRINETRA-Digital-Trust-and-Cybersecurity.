import { request, store } from "../lib/api";

export type QueueItem = { case_id: string; state: string; severity: string; priority: number; version: number;
  age_ms: number; created_ms: number; updated_ms: number; payment_id: string; payment_state: string; decision: string;
  amount_minor: number; amount_display: string; channel: string; beneficiary_masked: string; pending_proposals: number;
  hold_active: boolean };
export type Watermark = { cursor: number; as_of_ms: number };
export type Queue = { items: QueueItem[]; total: number; limit: number; offset: number; from_ms: number; to_ms: number;
  watermark: Watermark };

export type Evidence = { id: string; source: string; kind: string; status: string; model_id: string | null;
  revision: string | null; score_scale: string | null; score: number | null; flagged: boolean | null;
  review_only: boolean; created_ms: number; payload: any };
export type TimelineEvent = { seq: number; cursor: number | null; id: string; type: string; actor: string;
  prev_state: string | null; new_state: string | null; case_version: number; data: any; evidence_ids: string[];
  created_ms: number };
export type Proposal = { id: string; action: string; params: any; rationale: string; evidence_ids: string[]; tier: number;
  status: string; case_version: number; created_by: string; created_ms: number; reviewed_by: string | null;
  reviewed_ms: number | null; review_rationale: string | null };
export type Reason = { code: string; text: string; effect: string; signal: string | null };
export type CaseFile = {
  case: { id: string; state: string; severity: string; priority: number; version: number; hold_active: boolean;
          verdict: string | null; created_ms: number; updated_ms: number; first_disposition_ms: number | null; report: any };
  payment: { id: string; state: string; decision: string; policy_version: string; amount_minor: number;
             amount_display: string; channel: string; remark: string | null; created_ms: number; updated_ms: number;
             reasons: Reason[]; signals: Record<string, { status: string; review_only: boolean; flagged: boolean | null }>;
             settlement: { id: string; created_ms: number } | null;
             challenge: { status: string; expires_ms: number; attempts: number; max_attempts: number } | null };
  sender: { account_id: string; account_masked: string; account_created_ms: number; owner_ref: string };
  beneficiary: { name: string; masked: string; added_ms: number };
  restrictions: { id: string; scope_type: string; scope_id: string; reason: string }[];
  evidence: Evidence[];
  linked_transactions: { id: string; state: string; decision: string; amount_minor: number; amount_display: string;
                         created_ms: number; same_owner: boolean }[];
  timeline: TimelineEvent[];
  proposals: Proposal[];
  watch: { id: string; status: string; horizon_ms: number; interval_ms: number; next_due_ms: number; checks: number;
           created_ms: number; last_result: any } | null;
  adjudications: { id: string; label: string; reviewer: string; rationale: string; supersedes: string | null; created_ms: number }[];
  eligible_actions: { action: string; tier: number }[];
  watermark: Watermark;
};
export type Analytics = {
  from_ms: number; to_ms: number; interval_ms: number; watermark: Watermark;
  volume: { buckets: { start_ms: number; end_ms: number; ALLOW: number; STEP_UP: number; HOLD: number; BLOCK: number; total: number }[];
            totals: Record<string, number>; current_state: Record<string, number>; intervention_rate: number | null };
  queue: { open_by_priority_age: Record<string, Record<string, number>>; open_total: number;
           review_time: { n: number; p50_ms: number | null; p90_ms: number | null; mean_ms: number | null };
           watches: Record<string, number> };
  model_quality: { adjudicated_cases: number; rows: { signal: string; model_id: string | null; revision: string | null;
    tp: number; fp: number; tn: number; fn: number; abstain: number; n: number; precision: number | null; recall: number | null }[] };
  worker: { queued: number; leased: number; completed: number; failed: number; retries: number;
            oldest_pending_age_ms: number | null; measured_ms: number };
};
export type BucketRows = { items: { id: string; decision: string; state: string; amount_minor: number; amount_display: string;
  channel: string; created_ms: number; case_id: string | null }[]; watermark: Watermark };
export type ModelInfo = { models: { key: string; signal: string; model_id: string; revision: string; license: string;
  languages: string[]; enforce: boolean; status: string; reason: string; threshold: number }[]; policy_version: string };

const tok = store<{ token: string; name: string }>("trinetra.soc.session");
export const socSession = { get: () => tok.get(), set: (v: { token: string; name: string } | null) => tok.set(v) };
const t = () => tok.get()?.token ?? null;

export const soc = {
  login: (name: string, passcode: string) =>
    request<{ token: string; scope: string }>("/api/v2/soc/login", { method: "POST", body: { name, passcode } }),
  me: () => request<{ name: string; scope: string; tier: number; kill_switch: boolean }>("/api/v2/soc/me", { token: t() }),
  queue: (q: URLSearchParams, signal?: AbortSignal) => request<Queue>(`/api/v2/soc/cases?${q}`, { token: t(), signal }),
  caseFile: (id: string, signal?: AbortSignal) => request<CaseFile>(`/api/v2/soc/cases/${id}`, { token: t(), signal }),
  action: (id: string, body: { action: string; expected_version: number; rationale: string; params?: any; command_key: string }) =>
    request<any>(`/api/v2/soc/cases/${id}/actions`, { method: "POST", body, token: t() }),
  review: (pid: string, body: { decision: "approve" | "reject"; expected_version: number; rationale: string; command_key: string }) =>
    request<any>(`/api/v2/soc/proposals/${pid}/review`, { method: "POST", body, token: t() }),
  analytics: (from: number, to: number, tz: number, signal?: AbortSignal) =>
    request<Analytics>(`/api/v2/soc/analytics?from_ms=${from}&to_ms=${to}&tz_offset_min=${tz}`, { token: t(), signal }),
  rows: (from: number, to: number, decision?: string) =>
    request<BucketRows>(`/api/v2/soc/analytics/rows?from_ms=${from}&to_ms=${to}${decision ? `&decision=${decision}` : ""}`, { token: t() }),
  events: (after: number) => request<{ notices: Notice[]; watermark: Watermark }>(`/api/v2/soc/events?after=${after}`, { token: t() }),
  models: () => request<ModelInfo>("/api/v2/soc/models", { token: t() }),
  token: t,
};

export type Notice = { cursor: number; case_id: string; case_version: number; event: string; created_ms: number };
