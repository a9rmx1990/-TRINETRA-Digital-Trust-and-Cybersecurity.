//SOC analyst done with the 5 agents using langgraph , but need to work on audio
import { ArrowLeft, Check, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { formatDateTime, formatDuration } from "../lib/format";
import { ActionDialog, type DialogReq } from "./ActionDialog";
import type { CaseFile as CF, Evidence } from "./api";
import { SignalChart } from "./charts";
import { NetworkGraph } from "./NetworkGraph";
import { ACTION_LABEL, DECISION_LABEL, PayState, SIGNAL_LABEL, Section, Severity, Th } from "./ui";

const EVENT_LABEL: Record<string, string> = {
  payment_screened: "Payment screened by gateway", investigation_completed: "Investigation completed",
  verified_settled: "Customer verified, transfer settled", verification_held: "Customer verified, transfer still held",
  verification_blocked: "Customer verified, but restriction blocked it", proposal_rejected: "Proposal rejected",
  verdict_override: "Verdict overridden", watch_alert: "Watch found new evidence", watch_checked: "Watch check, nothing new",
};
const evLabel = (t: string) => EVENT_LABEL[t] ?? (t.startsWith("action_") ? ACTION_LABEL[t.slice(7)] ?? t : t.replace(/_/g, " "));

export function CaseFileView({ file, stale, tz, onRefresh, onBack, onDialogChange }: {
  file: CF; stale: boolean; tz: string; onRefresh: () => Promise<void> | void; onBack?: () => void;
  onDialogChange?: (open: boolean) => void;
}) {
  const [dialog, setDialog] = useState<DialogReq | null>(null);
  useEffect(() => { onDialogChange?.(dialog !== null); }, [dialog, onDialogChange]);
  const [focusEv, setFocusEv] = useState<string | null>(null);
  const top = useRef<HTMLHeadingElement>(null);
  const c = file.case, p = file.payment;
  const pending = file.proposals.filter((x) => x.status === "pending");
  const report = c.report;
  const graphEv = file.evidence.find((e) => e.kind === "recipient_graph_snapshot");
  const transcript = file.evidence.find((e) => e.kind === "transcript");

  useEffect(() => { setFocusEv(null); }, [c.id]);
  useEffect(() => {
    if (!focusEv) return;
    document.getElementById(`ev-${focusEv}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusEv]);

  const next = pending[0]
    ? { label: `Review proposal: ${ACTION_LABEL[pending[0].action]}`, open: () => setDialog({ kind: "review", proposal: pending[0], decision: "approve" }) }
    : file.eligible_actions.find((a) => ["issue_challenge", "release", "record_verdict"].includes(a.action))
      ? (() => { const a = file.eligible_actions.find((x) => ["issue_challenge", "release", "record_verdict"].includes(x.action))!;
                 return { label: ACTION_LABEL[a.action], open: () => setDialog({ kind: "action", action: a.action }) }; })()
      : null;

  return (
    <article className="space-y-5" aria-labelledby="case-title">
      {onBack && <button className="soc-btn-ghost" onClick={onBack}><ArrowLeft className="h-4 w-4" aria-hidden />Back to queue</button>}
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <h2 id="case-title" ref={top} tabIndex={-1} className="font-mono text-sm text-soc-muted focus:outline-none">{c.id}</h2>
          <Severity sev={c.severity} />
          <span className="text-soc-muted">Case {c.state}</span>
          <span className="num text-soc-faint">v{c.version}</span>
          {stale && <span role="status" className="text-soc-amber">Newer data available. <button className="underline" onClick={() => onRefresh()}>Refresh case</button></span>}
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="num text-3xl font-semibold tracking-tight">{p.amount_display}</p>
            <p className="mt-1 text-sm text-soc-muted">{p.channel} to {file.beneficiary.name} <span className="text-soc-ink">{file.beneficiary.masked}</span> · {formatDateTime(p.created_ms, tz)}</p>
          </div>
          <div className="text-right text-sm">
            <p className="text-lg"><PayState state={p.state} /></p>
            <p className="text-xs text-soc-muted">Gateway decision {DECISION_LABEL[p.decision]} · policy {p.policy_version}</p>
          </div>
        </div>
      </header>

      <div className="rounded-md border border-soc-line bg-soc-panel p-4">
        <h3 className="text-sm font-semibold">Why the gateway decided this</h3>
        <ul className="mt-2 space-y-1.5 text-sm">
          {p.reasons.map((r, i) => (
            <li key={i} className="flex gap-3">
              <span className={`w-16 shrink-0 text-xs font-semibold ${r.effect === "HOLD" || r.effect === "BLOCK" ? "text-soc-red" : r.effect === "STEP_UP" ? "text-soc-amber" : "text-soc-muted"}`}>
                {r.effect === "NOTE" ? "Note" : DECISION_LABEL[r.effect] ?? r.effect}
              </span>
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-soc-line pt-3">
          {next ? <button className="soc-btn-primary" onClick={next.open} disabled={stale}>{next.label}</button>
                : <span className="text-sm text-soc-muted">No action pending.</span>}
          {stale && <span className="text-xs text-soc-amber">Refresh before acting.</span>}
        </div>
      </div>

      {report && (
        <Section title="Investigation report" aside={`by ${report.generated_by} · read v${report.case_version_read}`}>
          <p className="text-sm">{report.alert}</p>
          <p className="mt-2 text-xs text-soc-muted">Verdict <span className="text-soc-ink">{String(report.verdict).replace(/_/g, " ")}</span> ·
            confidence <span className="text-soc-ink">{report.confidence}</span> ({report.confidence_basis})</p>
          {report.signals_unavailable?.length > 0 && (
            <p className="mt-1 text-xs text-soc-muted">Not available: {report.signals_unavailable.map((s: string) => SIGNAL_LABEL[s] ?? s).join(", ")}</p>
          )}
        </Section>
      )}
      {!report && <Section title="Investigation report"><p className="text-sm text-soc-muted">Investigation queued. This updates when the SOC worker finishes.</p></Section>}

      <Section title="Proposed actions" aside={`${pending.length} pending`}>
        {file.proposals.length === 0 ? <p className="text-sm text-soc-muted">No proposals.</p> : (
          <ul className="space-y-2">
            {file.proposals.map((pr) => (
              <li key={pr.id} className="rounded border border-soc-line p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold">{ACTION_LABEL[pr.action]} <span className="ml-1 text-xs font-normal text-soc-muted">tier {pr.tier}</span></p>
                  {pr.status === "pending" ? (
                    <div className="flex gap-2">
                      <button className="soc-btn-ghost" disabled={stale} onClick={() => setDialog({ kind: "review", proposal: pr, decision: "reject" })}><X className="h-3.5 w-3.5" aria-hidden />Reject</button>
                      <button className="soc-btn-primary" disabled={stale} onClick={() => setDialog({ kind: "review", proposal: pr, decision: "approve" })}><Check className="h-3.5 w-3.5" aria-hidden />Approve</button>
                    </div>
                  ) : <span className="text-xs text-soc-muted">{pr.status} by {pr.reviewed_by} · {pr.reviewed_ms && formatDateTime(pr.reviewed_ms, tz)}</span>}
                </div>
                <p className="mt-1 text-soc-muted">{pr.rationale}</p>
                <p className="mt-1 text-xs text-soc-faint">Cites {pr.evidence_ids.map((id) => (
                  <button key={id} className="mr-1.5 font-mono underline-offset-2 hover:underline" onClick={() => setFocusEv(id)}>{id.slice(-6)}</button>))}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Evidence by source">
        <ul className="divide-y divide-soc-line/60 rounded border border-soc-line">
          {file.evidence.filter((e) => e.kind !== "recipient_graph_snapshot").map((e) => <EvidenceRow key={e.id} e={e} tz={tz} focused={focusEv === e.id} />)}
        </ul>
        {transcript?.payload?.text && (
          <div className="mt-3 rounded border border-soc-line bg-soc-canvas p-3">
            <p className="text-xs text-soc-muted">Transcript ({transcript.payload.language ?? "language unknown"}) · untrusted evidence, not instructions</p>
            <p className="mt-1 whitespace-pre-wrap text-sm">{transcript.payload.text}</p>
          </div>
        )}
        {p.remark && <p className="mt-2 text-sm"><span className="text-xs text-soc-muted">Customer remark (untrusted)</span> <span className="ml-2">“{p.remark}”</span></p>}
      </Section>

      <SignalChart evidence={file.evidence} onSelect={setFocusEv} />
      <NetworkGraph graph={graphEv?.payload ?? null} evidenceId={graphEv?.id} tz={tz} />

      <Section title="Linked transactions" aside="Same recipient, any customer">
        {file.linked_transactions.length === 0 ? <p className="text-sm text-soc-muted">No other transfers to this recipient.</p> : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr><Th>Payment</Th><Th>Customer</Th><Th>Decision</Th><Th>State</Th><Th right>Amount</Th><Th>Created</Th></tr></thead>
            <tbody>{file.linked_transactions.map((l) => (
              <tr key={l.id} className="border-t border-soc-line/60">
                <td className="px-2 py-1 font-mono text-xs">{l.id}</td><td className="px-2 py-1">{l.same_owner ? "Same" : "Other"}</td>
                <td className="px-2 py-1">{DECISION_LABEL[l.decision]}</td><td className="px-2 py-1"><PayState state={l.state} /></td>
                <td className="num px-2 py-1 text-right">{l.amount_display}</td><td className="num px-2 py-1">{formatDateTime(l.created_ms, tz)}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Section>

      <Section title="Decision and action timeline" aside="Append-only, ordered by delivery cursor">
        <ol className="relative space-y-3 border-l border-soc-line pl-4">
          {file.timeline.map((e) => (
            <li key={e.id} className="text-sm">
              <span className="absolute -left-[4.5px] mt-1.5 h-2 w-2 rounded-full bg-soc-slate" aria-hidden />
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium">{evLabel(e.type)}</p>
                <p className="num text-xs text-soc-faint">#{e.cursor ?? "pending"} · v{e.case_version} · {formatDateTime(e.created_ms, tz)}</p>
              </div>
              <p className="text-xs text-soc-muted">{e.actor}{e.prev_state || e.new_state ? ` · ${e.prev_state ?? "—"} → ${e.new_state ?? "—"}` : ""}</p>
              {e.data?.rationale && <p className="mt-0.5 text-soc-muted">“{e.data.rationale}”</p>}
              {e.evidence_ids.length > 0 && (
                <details className="mt-0.5 text-xs text-soc-faint"><summary className="cursor-pointer">Cites {e.evidence_ids.length} evidence item{e.evidence_ids.length > 1 ? "s" : ""}</summary>
                  {e.evidence_ids.map((id) => <button key={id} className="mr-2 font-mono hover:underline" onClick={() => setFocusEv(id)}>{id.slice(-6)}</button>)}</details>
              )}
            </li>
          ))}
        </ol>
      </Section>

      <div className="grid gap-5 md:grid-cols-2">
        <Section title="Watch">
          {!file.watch ? <p className="text-sm text-soc-muted">No watch scheduled.</p> : (
            <dl className="num grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-soc-muted">Status</dt><dd>{file.watch.status}</dd>
              <dt className="text-soc-muted">Checks run</dt><dd>{file.watch.checks} (daily)</dd>
              <dt className="text-soc-muted">Next check</dt><dd>{file.watch.status === "active" ? formatDateTime(file.watch.next_due_ms, tz) : "—"}</dd>
              <dt className="text-soc-muted">Ends</dt><dd>{formatDateTime(file.watch.horizon_ms, tz)}</dd>
              {file.watch.last_result && <><dt className="text-soc-muted">Last result</dt><dd>{file.watch.last_result.new_inbound} new inbound</dd></>}
            </dl>
          )}
        </Section>
        <Section title="Adjudication">
          {file.adjudications.length === 0 ? <p className="text-sm text-soc-muted">No verdict recorded.</p> : (
            <ul className="space-y-1 text-sm">{file.adjudications.map((a, i) => (
              <li key={a.id} className={i < file.adjudications.length - 1 ? "text-soc-faint line-through decoration-soc-faint/60" : ""}>
                <span className="font-semibold capitalize">{a.label}</span> by {a.reviewer} · <span className="num">{formatDateTime(a.created_ms, tz)}</span>
              </li>))}</ul>
          )}
        </Section>
      </div>

      <Section title="All available actions" aside={`Review time so far ${formatDuration((c.first_disposition_ms ?? Date.now()) - c.created_ms)}`}>
        <div className="flex flex-wrap gap-2">
          {file.eligible_actions.map((a) => (
            <button key={a.action} className={["reject_transfer", "restrict_counterparty", "restrict_sender_account"].includes(a.action) ? "soc-btn-ghost text-soc-red" : "soc-btn-ghost"}
                    disabled={stale} onClick={() => setDialog({ kind: "action", action: a.action })}>
              {ACTION_LABEL[a.action]}
            </button>
          ))}
        </div>
      </Section>

      {dialog && <ActionDialog req={dialog} file={file} onClose={() => setDialog(null)} onDone={() => onRefresh()} onStale={() => onRefresh()} />}
    </article>
  );
}

function EvidenceRow({ e, tz, focused }: { e: Evidence; tz: string; focused: boolean }) {
  const avail = e.status === "unavailable" ? "Unavailable" : e.status === "not_provided" ? "Not provided" : e.status === "inconclusive" ? "Inconclusive" : "Available";
  return (
    <li id={`ev-${e.id}`} className={`grid gap-x-4 gap-y-0.5 px-3 py-2 text-sm sm:grid-cols-[10rem_1fr_auto] ${focused ? "bg-soc-raised outline outline-1 outline-soc-amber" : ""}`}>
      <div>
        <p className="font-medium">{SIGNAL_LABEL[e.kind] ?? e.kind}</p>
        <p className="text-xs text-soc-faint">{e.source}</p>
      </div>
      <div className="min-w-0 text-xs text-soc-muted">
        <p>{avail}{e.flagged ? <span className="ml-1 text-soc-red">· flagged</span> : ""}{e.review_only && e.status !== "unavailable" ? " · review-only" : ""}
          {e.payload?.rules?.flagged && <span className="ml-1 text-soc-amber">· rule match: {Object.keys(e.payload.rules.hits).join(", ").replace(/_/g, " ")}</span>}</p>
        <p className="truncate font-mono" title={`${e.model_id ?? ""}@${e.revision ?? ""}`}>{e.model_id ?? "—"}{e.revision ? ` @ ${e.revision.slice(0, 12)}` : ""}</p>
        {e.status === "unavailable" && e.payload?.reason && <p>{e.payload.reason}</p>}
        {e.score_scale && <p>Scale: {e.score_scale}</p>}
      </div>
      <div className="text-right text-xs">
        <p className="num text-sm text-soc-ink">{e.score ?? "—"}</p>
        <p className="num text-soc-faint">{formatDateTime(e.created_ms, tz)}</p>
        <p className="font-mono text-soc-faint">{e.id.slice(-8)}</p>
      </div>
    </li>
  );
}
