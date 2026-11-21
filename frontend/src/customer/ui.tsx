import { AlertTriangle, CheckCircle2, Clock3, Info, Lock, ShieldAlert, XCircle } from "lucide-react";
import { useId, type ReactNode } from "react";
import type { PaymentState, Receipt } from "./api";

export function Field({ label, hint, error, children }: {
  label: string; hint?: string; error?: string | null;
  children: (p: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-semibold text-ink">{label}</label>
      {children({ id, "aria-describedby": [hintId, errId].filter(Boolean).join(" ") || undefined, "aria-invalid": !!error })}
      {hint && !error && <p id={hintId} className="text-sm text-muted">{hint}</p>}
      {error && <p id={errId} className="flex items-start gap-1.5 text-sm text-bad"><XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />{error}</p>}
    </div>
  );
}

const STATE: Record<PaymentState, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  SETTLED: { label: "Approved", cls: "bg-ok-soft text-ok", Icon: CheckCircle2 },
  VERIFICATION_REQUIRED: { label: "Verification needed", cls: "bg-warn-soft text-warn", Icon: Lock },
  HELD: { label: "Under review", cls: "bg-warn-soft text-warn", Icon: Clock3 },
  BLOCKED: { label: "Blocked", cls: "bg-bad-soft text-bad", Icon: ShieldAlert },
  REJECTED: { label: "Not completed", cls: "bg-[#EEF0F4] text-muted", Icon: XCircle },
};

export function StateBadge({ state, direction }: { state: PaymentState; direction: Receipt["direction"] }) {
  const s = STATE[state];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${s.cls}`}>
      <s.Icon className="h-3.5 w-3.5" aria-hidden />{state === "SETTLED" && direction === "outgoing" ? "Settled" : s.label}
    </span>
  );
}

export function stateLabel(state: PaymentState) {
  return STATE[state].label;
}

export function Notice({ tone = "info", title, children, action }: {
  tone?: "info" | "warn" | "bad" | "ok"; title?: string; children?: ReactNode; action?: ReactNode;
}) {
  const map = {
    info: { cls: "border-[#CFDAF5] bg-primary-soft text-ink", Icon: Info, ic: "text-primary" },
    warn: { cls: "border-[#EBD3A6] bg-warn-soft text-ink", Icon: AlertTriangle, ic: "text-warn" },
    bad: { cls: "border-[#F0C3BE] bg-bad-soft text-ink", Icon: XCircle, ic: "text-bad" },
    ok: { cls: "border-[#BFDCCB] bg-ok-soft text-ink", Icon: CheckCircle2, ic: "text-ok" },
  }[tone];
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={`flex gap-3 rounded-md border px-3.5 py-3 text-sm ${map.cls}`}>
      <map.Icon className={`mt-0.5 h-4 w-4 shrink-0 ${map.ic}`} aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className="text-muted">{children}</div>}
        {action && <div className="pt-1">{action}</div>}
      </div>
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity=".25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`workspace-panel ${className}`}>{children}</section>;
}
