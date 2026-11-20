/**
 * api.ts — typed fetch wrappers for TRINETRA backend
 * All calls target http://localhost:8000 directly (no Vite proxy for WS safety)
 */
import type {
  TransactionPayload,
  InterceptionResponse,
  CytoscapeGraph,
  Metrics,
  ScenarioMeta,
} from './types';

export const BASE = 'http://localhost:8000';

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<{ status: string }> {
  return json('/health');
}

export async function getMetrics(): Promise<Metrics> {
  return json('/api/v1/metrics');
}

export async function getScenarios(): Promise<ScenarioMeta[]> {
  return json('/api/v1/scenarios');
}

export async function triggerScenario(id: string): Promise<InterceptionResponse> {
  return json(`/api/v1/scenarios/trigger/${id}`, { method: 'POST' });
}

export async function intercept(payload: TransactionPayload): Promise<InterceptionResponse> {
  const completePayload: Required<Pick<TransactionPayload, 'transaction_id'>> & TransactionPayload = {
    transaction_id: payload.transaction_id ?? `TX-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`,
    ...payload,
  };
  return json('/api/v1/intercept', {
    method: 'POST',
    body: JSON.stringify(completePayload),
  });
}

export async function getGraph(focus_account?: string): Promise<CytoscapeGraph> {
  const qs = focus_account ? `?focus_account=${encodeURIComponent(focus_account)}` : '';
  return json(`/api/v1/graph/mule-network${qs}`);
}

export async function socOverride(
  account: string,
  action: 'CONFIRM_FREEZE' | 'RELEASE_HOLD',
  analyst_id = 'SOC-ANALYST-01',
): Promise<unknown> {
  return json('/api/v1/soc/override', {
    method: 'POST',
    body: JSON.stringify({ account, action, analyst_id }),
  });
}
