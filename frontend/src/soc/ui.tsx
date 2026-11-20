import { AlertOctagon, AlertTriangle, CheckCircle2, CircleDashed, Clock3, Lock, Minus, ShieldAlert, XCircle } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

export const PAY_STATE: Record<string, { label: string; cls: string; Icon: typeof Lock }> = {
  SETTLED: { label: "Settled", cls: "text-soc-slate", Icon: CheckCircle2 },
  VERIFICATION_REQUIRED: { label: "Step-up pending", cls: "text-soc-amber", Icon: Lock },
  HELD: { label: "Held", cls: "text-soc-amber", Icon: Clock3 },
  BLOCKED: { label: "Blocked", cls: "text-soc-red", Icon: ShieldAlert },
  REJECTED: { label: "Rejected", cls: "text-soc-faint", Icon: XCircle },
};
export const DECISION_LABEL: Record<string, string> = { ALLOW: "Allow", STEP_UP: "Step-up", HOLD: "Hold", BLOCK: "Block" };

export function PayState({ state }: { state: string }) {
  const s = PAY_STATE[state] ?? { label: state, cls: "text-soc-muted", Icon: Minus };
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap ${s.cls}`}><s.Icon className="h-3.5 w-3.5" aria-hidden />{s.label}</span>;
}

export function Severity({ sev }: { sev: string }) {
  const m = sev === "high" ? { cls: "text-soc-red", Icon: AlertOctagon, l: "High" }
    : sev === "medium" ? { cls: "text-soc-amber", Icon: AlertTriangle, l: "Medium" }
    : { cls: "text-soc-slate", Icon: CircleDashed, l: "Low" };
  return <span className={`inline-flex items-center gap-1.5 ${m.cls}`}><m.Icon className="h-3.5 w-3.5" aria-hidden />{m.l}</span>;
}

export function Section({ title, aside, children, id }: { title: string; aside?: ReactNode; children: ReactNode; id?: string }) {
  const hid = useId();
  return (
    <section aria-labelledby={hid} id={id} className="border-t border-soc-line pt-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 id={hid} className="text-sm font-semibold text-soc-ink">{title}</h3>
        {aside && <div className="text-xs text-soc-muted">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export type QueryState = "loading" | "ok" | "empty" | "unauthorized" | "stale" | "failed";

export function DataState({ state, onRetry, emptyText }: { state: QueryState; onRetry?: () => void; emptyText?: string }) {
  if (state === "ok") return null;
  const m: Record<Exclude<QueryState, "ok">, { t: string; cls: string }> = {
    loading: { t: "Loading…", cls: "text-soc-muted" },
    empty: { t: emptyText ?? "No matching data for these filters.", cls: "text-soc-muted" },
    unauthorized: { t: "Your analyst session does not allow this view. Sign in again.", cls: "text-soc-red" },
    stale: { t: "Showing the last successful result. Refresh failed.", cls: "text-soc-amber" },
    failed: { t: "The query failed.", cls: "text-soc-red" },
  };
  return (
    <div role={state === "failed" || state === "unauthorized" ? "alert" : "status"}
         className={`flex items-center justify-between gap-3 rounded border border-dashed border-soc-line px-3 py-4 text-sm ${m[state].cls}`}>
      <span>{m[state].t}</span>
      {onRetry && (state === "failed" || state === "stale") && <button className="soc-btn-ghost" onClick={onRetry}>Retry</button>}
    </div>
  );
}

/** Every chart has a text table equivalent; the toggle is a real button with pressed state. */
export function ChartFrame({ title, description, chart, table, aside }: {
  title: string; description: string; chart: ReactNode; table: ReactNode; aside?: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const hid = useId();
  return (
    <figure aria-labelledby={hid} className="workspace-panel min-w-0 p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 id={hid} className="text-sm font-semibold text-soc-ink">{title}</h3>
          <p className="mt-0.5 text-xs text-soc-muted">{description}</p>
        </div>
        <div className="flex items-center gap-3">
          {aside}
          <button className="soc-btn-ghost px-2 py-1 text-xs" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
            {asTable ? "Show chart" : "Show table"}
          </button>
        </div>
      </div>
      {asTable ? <div className="overflow-auto">{table}</div> : chart}
    </figure>
  );
}

export function Th({ children, right = false, className = "", sort }: {
  children: ReactNode; right?: boolean; className?: string; sort?: "ascending" | "descending" | "none";
}) {
  return <th scope="col" aria-sort={sort} className={`px-2 py-1.5 text-xs font-medium text-soc-muted ${right ? "text-right" : "text-left"} ${className}`}>{children}</th>;
}

export const SIGNAL_LABEL: Record<string, string> = {
  voice_authenticity: "Voice authenticity", speech_content: "Spoken content", typed_remark: "Typed remark",
  recipient_graph: "Recipient network", transcript: "Transcript", capture_quality: "Capture quality",
  recipient_graph_snapshot: "Network snapshot",
};
export const ACTION_LABEL: Record<string, string> = {
  issue_challenge: "Issue verification code", place_hold: "Place hold", release: "Release transfer",
  reject_transfer: "Reject transfer", restrict_counterparty: "Restrict recipient", restrict_sender_account: "Restrict sender account",
  lift_restriction: "Lift restriction", record_verdict: "Record verdict", close_case: "Close case", reopen_case: "Reopen case",
};
export const ACTION_EFFECT: Record<string, string> = {
  issue_challenge: "Creates a 6-digit code for the customer. It is shown to you once and is valid for 15 minutes. Any earlier code is revoked.",
  place_hold: "Keeps the transfer from settling even after the customer verifies. Reversible with Release.",
  release: "Clears the hold. A held transfer settles immediately after restrictions are rechecked.",
  reject_transfer: "Ends the transfer without moving money. Active codes are revoked. Cannot be undone.",
  restrict_counterparty: "Blocks all transfers to this recipient from every customer. An unsettled transfer in this case becomes blocked.",
  restrict_sender_account: "Blocks transfers from the sender's account. An unsettled transfer in this case becomes blocked.",
  lift_restriction: "Removes the selected restriction for future transfers. Past outcomes do not change.",
  record_verdict: "Records your adjudication. A new verdict supersedes earlier ones; the earlier record stays in the trail.",
  close_case: "Closes the case. If a watch is active the case moves to monitoring and can reopen on new evidence.",
  reopen_case: "Returns the case to the open queue.",
};
