import { request, store } from "../lib/api";

export type Account = { id: string; display_name: string; account_ref: string; account_ref_masked: string;
                        status: string; created_ms: number };
export type Beneficiary = { id: string; display_name: string; account_ref_masked: string; created_ms: number };
export type CallStatus = { id: string; status: "open" | "finished" | "expired" | "deleted"; created_ms: number;
  expires_ms: number; finished_ms: number | null; duration_ms: number; voiced_ms: number; usable: boolean;
  quality_reason: string | null; language: string | null; language_supported: boolean | null;
  transcript_status: string | null; fresh_for_submission: boolean; used_by_payment: boolean };
export type PaymentState = "SETTLED" | "VERIFICATION_REQUIRED" | "HELD" | "BLOCKED" | "REJECTED";
export type Receipt = { payment_id: string; reference: string; state: PaymentState; amount_minor: number;
  direction: "incoming" | "outgoing";
  amount_display: string; currency: string; channel: string; beneficiary_name: string; beneficiary_masked: string;
  created_ms: number; updated_ms: number; message: string; next_action: string; replayed?: boolean; analyst_verified?: boolean;
  challenge?: { status: string; expires_ms: number; attempts_left: number; delivery_code?: string } | null };
export type VerifyResult = { outcome: string; payment: Receipt };

const tokenStore = store<string>("trinetra.customer.token");

export const session = {
  token: () => tokenStore.get(),
  clear: () => tokenStore.set(null),
  async ensure(): Promise<string> {
    const t = tokenStore.get();
    if (t) return t;
    const r = await request<{ token: string }>("/api/v2/session", { method: "POST" });
    tokenStore.set(r.token);
    return r.token;
  },
};

const t = () => session.token();

export const api = {
  me: () => request<{ accounts: Account[]; beneficiaries: Beneficiary[] }>("/api/v2/me", { token: t() }),
  createAccount: (display_name: string) =>
    request<Account>("/api/v2/accounts", { method: "POST", body: { display_name }, token: t() }),
  addBeneficiary: (display_name: string, account_ref: string) =>
    request<Beneficiary>("/api/v2/beneficiaries", { method: "POST", body: { display_name, account_ref }, token: t() }),
  removeBeneficiary: (id: string) => request<void>(`/api/v2/beneficiaries/${id}`, { method: "DELETE", token: t() }),
  startCall: () => request<CallStatus>("/api/v2/calls", { method: "POST", body: { consent: true }, token: t() }),
  sendPcm: (id: string, chunk: ArrayBuffer) =>
    request<{ bytes: number }>(`/api/v2/calls/${id}/pcm`, { method: "POST", raw: chunk, token: t(),
      headers: { "Content-Type": "application/octet-stream" } }),
  finishCall: (id: string) => request<CallStatus>(`/api/v2/calls/${id}/finish`, { method: "POST", token: t(), timeoutMs: 60_000 }),
  getCall: (id: string) => request<CallStatus>(`/api/v2/calls/${id}`, { token: t() }),
  deleteCall: (id: string) => request<void>(`/api/v2/calls/${id}`, { method: "DELETE", token: t() }),
  requestMoney: (key: string, body: { account_id: string; beneficiary_id: string; amount_minor: number; channel: string;
                                remark: string | null; call_id: string }) =>
    request<Receipt>("/api/v2/payment-requests", { method: "POST", body, token: t(), headers: { "Idempotency-Key": key } }),
  lookup: (key: string) => request<Receipt>(`/api/v2/payments/lookup?key=${encodeURIComponent(key)}`, { token: t() }),
  payments: (before?: number) =>
    request<{ items: Receipt[]; next_before_ms: number | null }>(`/api/v2/payments${before ? `?before_ms=${before}` : ""}`, { token: t() }),
  payment: (id: string, signal?: AbortSignal) => request<Receipt>(`/api/v2/payments/${id}`, { token: t(), signal }),
  verify: (id: string, code: string) =>
    request<VerifyResult>(`/api/v2/payments/${id}/verify`, { method: "POST", body: { code }, token: t() }),
};
