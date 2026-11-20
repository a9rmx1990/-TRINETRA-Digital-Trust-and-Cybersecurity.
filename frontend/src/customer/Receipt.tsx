import { Check, CheckCircle2, Clock3, Lock, ShieldAlert, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { navigate } from "../lib/router";
import { api, type Receipt } from "./api";
import { Notice, Spinner, StateBadge } from "./ui";

const HEAD = {
  SETTLED: { Icon: CheckCircle2, cls: "text-ok", title: "Request approved", message: "The incoming transfer settled in the sandbox." },
  VERIFICATION_REQUIRED: { Icon: Lock, cls: "text-warn", title: "Waiting for verification", message: "The analyst is reviewing your money request." },
  HELD: { Icon: Clock3, cls: "text-warn", title: "Request under review", message: "The analyst is reviewing your request." },
  BLOCKED: { Icon: ShieldAlert, cls: "text-bad", title: "Request blocked", message: "An account restriction prevented approval." },
  REJECTED: { Icon: XCircle, cls: "text-muted", title: "Request declined", message: "Your request was declined after review." },
} as const;

function useReceiptPolling(paymentId: string, enabled: boolean, onResult: (receipt: Receipt) => void) {
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(async () => {
        try {
          const current = await api.payment(paymentId, controller.signal);
          if (!controller.signal.aborted) onResult(current);
        } catch { /* Retry on the next poll. */ }
        if (!controller.signal.aborted) schedule();
      }, 3000);
    };
    schedule();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [enabled, paymentId, onResult]);
}

export function ReceiptView({ receipt: initial, onNew }: { receipt: Receipt; onNew?: () => void }) {
  const [r, setR] = useState(initial);
  const [refreshing, setRefreshing] = useState(false);
  const [showVerified, setShowVerified] = useState(false);
  const h = HEAD[r.state];
  const outgoing = r.direction === "outgoing";
  const waiting = r.state === "VERIFICATION_REQUIRED";
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => { ref.current?.focus(); }, [r.state]);
  useEffect(() => { setR(initial); setShowVerified(false); }, [initial]);
  const receiveStatus = useCallback((current: Receipt) => {
    setR(current);
    if (current.analyst_verified) setShowVerified(true);
  }, []);
  useReceiptPolling(r.payment_id, waiting && !outgoing, receiveStatus);

  async function refresh() {
    setRefreshing(true);
    try { setR(await api.payment(r.payment_id)); } finally { setRefreshing(false); }
  }

  return (
    <div className="mx-auto max-w-xl space-y-5 rise">
      <div className="space-y-3">
        <h.Icon className={`h-9 w-9 ${h.cls}`} aria-hidden />
        <h1 ref={ref} tabIndex={-1} className="workspace-title text-3xl focus:outline-none">
          {outgoing ? "Outgoing transfer" : r.analyst_verified ? "Request verified" : h.title}
        </h1>
        <p className="text-base text-[#3A4458]">{outgoing ? r.message : h.message}</p>
        {r.replayed && <p className="text-sm text-muted">This receipt is for the request you already submitted.</p>}
      </div>
      <div className="workspace-panel">
        <div className="flex items-baseline justify-between gap-4 border-b border-line px-5 py-4">
          <StateBadge state={r.state} direction={r.direction} />
          <span className="num text-3xl font-semibold tracking-tight text-ink">{r.amount_display}</span>
        </div>
        <dl className="divide-y divide-line px-5 text-base">
          <div className="flex justify-between gap-4 py-2.5"><dt className="text-sm text-muted">{outgoing ? "Recipient" : "Requested from"}</dt>
            <dd className="text-right">{r.beneficiary_name} <span className="text-muted">{r.beneficiary_masked}</span></dd></div>
          <div className="flex justify-between gap-4 py-2.5"><dt className="text-sm text-muted">Reference</dt>
            <dd className="font-mono text-sm">{r.reference}</dd></div>
          <div className="flex justify-between gap-4 py-2.5"><dt className="text-sm text-muted">Channel</dt><dd>{r.channel}</dd></div>
          <div className="flex justify-between gap-4 py-2.5"><dt className="text-sm text-muted">Submitted</dt>
            <dd className="num">{formatDateTime(r.created_ms)}</dd></div>
        </dl>
      </div>

      {waiting && (outgoing ? <VerifyPanel receipt={r} onResult={setR} />
        : <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Spinner />This receipt updates automatically after analyst verification.
        </p>)}

      <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex justify-center">
        {showVerified && <div className="verification-pop workspace-panel pointer-events-auto flex w-full max-w-md items-center gap-3 p-4">
          <span className="verification-tick grid h-12 w-12 shrink-0 place-items-center rounded-full bg-ok-soft text-ok">
            <Check size={30} strokeWidth={3} aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1"><p className="font-semibold text-ok">Verified</p>
            <p className="text-sm text-muted">{r.amount_display} received in your sandbox account.</p>
          </div>
          <button type="button" className="btn-quiet" onClick={() => setShowVerified(false)} aria-label="Dismiss verification confirmation">
            <X size={18} aria-hidden="true" />
          </button>
        </div>}
      </div>

      <div className="flex flex-wrap gap-2">
        {r.state === "HELD" && (
          <button className="btn-primary" onClick={refresh} disabled={refreshing}>{refreshing && <Spinner />}Check status</button>
        )}
        {(r.state === "SETTLED" || r.state === "REJECTED" || r.state === "BLOCKED") && (
          <button className="btn-primary" onClick={() => navigate("/history")}>View request history</button>
        )}
        {r.state !== "SETTLED" && r.state !== "REJECTED" && r.state !== "BLOCKED" && (
          <button className="btn-secondary" onClick={() => navigate("/history")}>View request history</button>
        )}
        {onNew && <button className="btn-quiet" onClick={onNew}>Start another request</button>}
      </div>
    </div>
  );
}

const OUTCOME: Record<string, { tone: "bad" | "warn" | "info"; text: string }> = {
  incorrect: { tone: "bad", text: "That code is not correct." },
  expired: { tone: "warn", text: "This code has expired. Ask the analyst for a new one." },
  locked: { tone: "bad", text: "Too many incorrect attempts. Ask the analyst to issue a new code." },
  used: { tone: "info", text: "This code was already used." },
  revoked: { tone: "warn", text: "This code was replaced. Use the newest code you received." },
  no_challenge: { tone: "info", text: "Waiting for analyst approval. The code will appear here when it is ready." },
  held: { tone: "info", text: "Code accepted. Your request is still under review." },
  blocked: { tone: "bad", text: "Code accepted. An account restriction blocked your request." },
};

export function VerifyPanel({ receipt, onResult }: { receipt: Receipt; onResult: (r: Receipt) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "bad" | "warn" | "info"; text: string } | null>(null);
  const id = useId();
  const ch = receipt.challenge;
  const expired = ch ? ch.status === "expired" || (ch.status === "active" && ch.expires_ms < Date.now()) : false;
  const active = ch?.status === "active" && !expired;

  useReceiptPolling(receipt.payment_id, !busy, onResult);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) {
      setMsg({ tone: "bad", text: "Enter the 6-digit code." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.verify(receipt.payment_id, code);
      onResult(res.payment);
      if (res.outcome !== "verified") {
        const left = res.payment.challenge?.attempts_left;
        const o = OUTCOME[res.outcome] ?? { tone: "info" as const, text: HEAD[res.payment.state].message };
        setMsg(res.outcome === "incorrect" && left != null ? { ...o, text: `${o.text} ${left} attempt${left === 1 ? "" : "s"} left.` } : o);
      }
      setCode("");
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Verification failed." });
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    try {
      onResult(await api.payment(receipt.payment_id));
      setMsg(null);
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Could not refresh code status." });
    } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-line bg-white p-5" aria-labelledby={`${id}-h`}>
      <div className="space-y-1">
        <h2 id={`${id}-h`} className="text-lg font-semibold text-ink">{receipt.direction === "outgoing" ? "Transfer verification" : "Request verification"}</h2>
        <p className="text-sm text-muted">Your sandbox code appears here after an analyst approves verification.</p>
      </div>
      <div className="text-sm" aria-live="polite">
        {active && ch?.delivery_code && (
          <div className="mb-2 rounded-lg bg-primary-soft px-4 py-3 text-ink">
            <p className="font-semibold">Your sandbox verification code</p>
            <p className="num font-mono text-2xl font-semibold tracking-[0.2em]">{ch.delivery_code}</p>
          </div>
        )}
        {active && ch ? <p>Code valid until <span className="num font-semibold">{formatDateTime(ch.expires_ms)}</span> · {ch.attempts_left} attempts left</p>
          : expired ? <p className="text-warn">This code expired. The receipt will show a new code once an analyst issues one.</p>
          : ch?.status === "locked" ? <p className="text-bad">Too many attempts. The receipt will show a new code once an analyst issues one.</p>
          : <p className="text-muted">Waiting for analyst approval. This receipt updates automatically.</p>}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {active && <><div className="space-y-1.5">
          <label htmlFor={id} className="block text-sm font-semibold text-ink">Verification code</label>
          <input id={id} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                 onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                 className="field-input num w-40 text-center text-xl tracking-[0.3em]" aria-invalid={msg?.tone === "bad"} disabled={busy} />
        </div>
        <button type="submit" className="btn-primary" disabled={busy || code.length !== 6}>{busy && <Spinner />}Verify</button></>}
        <button type="button" className="btn-quiet" onClick={refresh} disabled={busy}>Refresh code status</button>
      </div>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </form>
  );
}
