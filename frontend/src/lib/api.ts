/** Thin fetch client. Server errors arrive as {detail: {code, message, field?}}. */

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public field?: string,
              public extra: Record<string, unknown> = {}) {
    super(message);
  }
  get isNetwork() {
    return this.status === 0;
  }
}

type Opts = { method?: string; body?: unknown; raw?: BodyInit; token?: string | null; headers?: Record<string, string>;
              signal?: AbortSignal; timeoutMs?: number };

export async function request<T>(path: string, o: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { ...(o.headers ?? {}) };
  if (o.token) headers.Authorization = `Bearer ${o.token}`;
  let body: BodyInit | undefined = o.raw;
  if (o.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(o.body);
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), o.timeoutMs ?? 20_000);
  o.signal?.addEventListener("abort", () => ctrl.abort());
  let res: Response;
  try {
    res = await fetch(path, { method: o.method ?? "GET", headers, body, signal: ctrl.signal });
  } catch {
    throw new ApiError(0, "network", "The connection was interrupted. Your request may not have reached the bank.");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data && data.detail) || {};
    const { code = "error", message = "Something went wrong. Try again.", field, ...extra } =
      typeof d === "object" ? d : { message: String(d) };
    throw new ApiError(res.status, code, message, field, extra);
  }
  return data as T;
}

export function store<T>(key: string) {
  return {
    get(): T | null {
      try {
        const v = localStorage.getItem(key);
        return v ? (JSON.parse(v) as T) : null;
      } catch {
        return null;
      }
    },
    set(v: T | null) {
      try {
        if (v === null) localStorage.removeItem(key);
        else localStorage.setItem(key, JSON.stringify(v));
      } catch {
        /* storage unavailable: session-only */
      }
    },
  };
}

export function newKey(): string {
  return crypto.randomUUID().replace(/-/g, "");
}
