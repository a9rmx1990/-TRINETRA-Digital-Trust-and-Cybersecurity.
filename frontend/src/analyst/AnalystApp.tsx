import { ArrowLeft, ArrowRight, Check, ChevronRight, RefreshCw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { ApiError, request } from "../lib/api";
import type { CaseFile, Queue } from "../soc/api";
import "./analyst.css";

const endpoint = "/api/v2/analyst";
const sessionKey = "trinetra.analyst.workspace";
const roles = [
  { id: "triage", name: "Triage" },
  { id: "investigator", name: "Investigator" },
  { id: "decision", name: "Decision" },
  { id: "monitor", name: "Monitor" },
  { id: "reporter", name: "Reporter" },
] as const;

type Finding = { summary: string; confidence: string; evidence_refs: string[]; next_step: string };
type Analysis = { id: string; case_version: number; model: string; findings: Record<string, Finding>;
  created_ms: number; traced: number; disposition: string | null; note: string | null };
type Detail = Pick<CaseFile, "case" | "beneficiary" | "watch" | "linked_transactions"> & {
  customer: CaseFile["sender"];
  payment: CaseFile["payment"] & { direction: "incoming" | "outgoing" };
  suspicion_level: "low" | "elevated" | "high" | "inconclusive";
  timeline: Pick<CaseFile["timeline"][number], "id" | "type" | "actor" | "created_ms">[];
  evidence: Omit<CaseFile["evidence"][number], "payload">[]; run: Analysis | null;
  verification: { available: boolean; delivered_until_ms: number | null; verified_run_id: string | null };
};
type Status = { model: string; tracing: boolean; unavailable_reason: string | null };
type Filters = { state: string; severity: string; days: string };
type CaseUpdate = { kind: "analysis" } | { kind: "review"; runId: string; disposition: string; note: string }
  | { kind: "send_code"; rationale: string } | { kind: "verification"; runId: string };
const initialFilters = { state: "", severity: "", days: "30" };
const label = (s: string) => s.replaceAll("_", " ");
const date = (ms: number) => new Date(ms).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const message = (e: unknown) => e instanceof Error ? e.message : "Something went wrong.";

export function AnalystApp() {
  const [token, setToken] = useState(() => sessionStorage.getItem(sessionKey));
  function session(value: string | null) {
    if (value) sessionStorage.setItem(sessionKey, value);
    else sessionStorage.removeItem(sessionKey);
    setToken(value);
  }
  return <div className="aw">
    <header className="workspace-bar aw-bar">
      <div className="aw-brand"><span className="workspace-brand">Trinetra</span><span>Analyst workspace</span></div>
      {token && <button className="aw-button aw-quiet" onClick={() => session(null)}>Sign out</button>}
    </header>
    {token ? <Workspace token={token} signOut={() => session(null)} /> : <Login onLogin={session} />}
  </div>;
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const fields = new FormData(event.currentTarget);
    try {
      const { token } = await request<{ token: string }>(endpoint + "/login", {
        method: "POST", body: { username: fields.get("username"), password: fields.get("password") },
      });
      onLogin(token);
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  return <main className="aw-login workspace-wash"><form className="workspace-panel" onSubmit={submit}>
    <h1 className="workspace-title">Analyst sign-in</h1>
    <label>Username<input name="username" defaultValue="admin" autoComplete="username" required /></label>
    <label>Workspace password<input name="password" type="password" autoComplete="current-password" required /></label>
    {error && <p className="aw-error" role="alert">{error}</p>}
    <button className="aw-button aw-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
  </form></main>;
}

function Workspace({ token, signOut }: { token: string; signOut: () => void }) {
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [queue, setQueue] = useState<Queue | null>(null);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [queueError, setQueueError] = useState("");
  const [caseError, setCaseError] = useState("");
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState<CaseUpdate["kind"] | null>(null);
  const busy = operation !== null;

  useEffect(() => {
    const ctrl = new AbortController();
    const query = new URLSearchParams({ days: filters.days, offset: String(offset) });
    if (filters.state) query.set("state", filters.state);
    if (filters.severity) query.set("severity", filters.severity);
    setLoading(true);
    setQueueError("");
    Promise.all([
      request<Queue>(endpoint + "/cases?" + query, { token, signal: ctrl.signal }),
      request<Status>(endpoint + "/status", { token, signal: ctrl.signal }),
    ]).then(([next, readiness]) => {
      if (ctrl.signal.aborted) return;
      setQueue(next);
      setStatus(readiness);
      setSelected(id => next.items.some(item => item.case_id === id) ? id : next.items[0]?.case_id ?? "");
    }).catch(e => {
      if (ctrl.signal.aborted) return;
      if (e instanceof ApiError && e.status === 401) signOut();
      else setQueueError(message(e));
    }).finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
    // A session change remounts the workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filters, offset, refresh]);

  useEffect(() => {
    setDetail(null);
    setCaseError("");
    if (!selected) return;
    const ctrl = new AbortController();
    request<Detail>(endpoint + "/cases/" + encodeURIComponent(selected), { token, signal: ctrl.signal })
      .then(value => { if (!ctrl.signal.aborted) setDetail(value); })
      .catch(e => {
        if (ctrl.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) signOut();
        else setCaseError(message(e));
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, token, refresh]);

  function filter(key: keyof Filters, value: string) {
    setFilters(old => ({ ...old, [key]: value }));
    setOffset(0);
  }

  async function updateCase(update: CaseUpdate) {
    if (!detail || busy) return;
    const path = endpoint + "/cases/" + encodeURIComponent(detail.case.id);
    const version = detail.case.version;
    let suffix = "/analysis";
    let body: Record<string, unknown> | undefined;
    if (update.kind === "verification") {
      suffix = "/verify";
      body = { expected_version: version, analysis_run_id: update.runId };
    } else if (update.kind === "send_code") {
      suffix = "/verification-code";
      body = { expected_version: version, rationale: update.rationale };
    } else if (update.kind === "review") {
      suffix = "/analysis/" + update.runId + "/review";
      body = { disposition: update.disposition, note: update.note };
    }
    setOperation(update.kind);
    setCaseError("");
    try {
      await request(path + suffix, {
        token, method: "POST", body, timeoutMs: update.kind === "analysis" ? 80_000 : undefined,
      });
      setRefresh(value => value + 1);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) signOut();
      else setCaseError(message(e));
    } finally { setOperation(null); }
  }

  const activeDetail = detail?.case.id === selected ? detail : null;
  return <main className="aw-main">
    <div className="aw-heading">
      <h1 className="workspace-title">Case investigations</h1>
      <button className="aw-button" disabled={loading || busy} onClick={() => setRefresh(value => value + 1)}>
        <RefreshCw size={16} aria-hidden="true" /> Refresh
      </button>
    </div>
    <div className="aw-status">
      <span><strong>{queue ? queue.total.toLocaleString() : "—"}</strong> matching cases</span>
      <span><strong>{status?.model ?? "Gemini"}</strong>{status?.unavailable_reason && " · setup required"}</span>
      <span>LangSmith {status ? status.tracing ? "enabled" : "off" : "—"}</span>
    </div>
    {queueError && <p className="aw-error" role="alert">{queueError}</p>}
    <div className="aw-layout">
      <aside className="aw-card aw-queue" aria-label="Case queue">
        <div className="aw-section-title"><h2>Case queue</h2></div>
        <fieldset className="aw-filters" disabled={busy}>
          <legend className="sr-only">Queue filters</legend>
          <label>State<select value={filters.state} onChange={e => filter("state", e.target.value)}>
            <option value="">All states</option><option value="needs_action">Needs action</option><option value="open">Open</option>
            <option value="monitoring">Monitoring</option><option value="closed">Closed</option>
          </select></label>
          <label>Severity<select value={filters.severity} onChange={e => filter("severity", e.target.value)}>
            <option value="">All levels</option>{["critical", "high", "medium", "low"].map(s => <option key={s} value={s}>{label(s)}</option>)}
          </select></label>
          <label>Period<select value={filters.days} onChange={e => filter("days", e.target.value)}>
            <option value="7">7 days</option><option value="30">30 days</option><option value="365">365 days</option>
          </select></label>
        </fieldset>
        {loading && <p className="aw-empty" role="status">Loading cases…</p>}
        {!loading && !queueError && !queue?.items.length && <p className="aw-empty">No cases match these filters.</p>}
        {!loading && queue?.items.map(item => <button key={item.case_id} aria-pressed={selected === item.case_id}
          disabled={busy} className="aw-case-row" onClick={() => setSelected(item.case_id)}>
          <span><strong>{item.amount_display}</strong><small>{item.case_id}</small></span>
          <span><span className="aw-chip" data-tone={item.severity}>{label(item.severity)}</span>
            <small>{label(item.state)}</small></span><ChevronRight size={15} aria-hidden="true" />
        </button>)}
        {queue && !loading && queue.total > queue.limit && <div className="aw-pagination">
          <button className="aw-button" aria-label="Previous page" disabled={offset === 0 || busy}
            onClick={() => setOffset(offset - queue.limit)}><ArrowLeft size={16} /></button>
          <span>{offset + 1}–{Math.min(offset + queue.limit, queue.total)} of {queue.total}</span>
          <button className="aw-button" aria-label="Next page" disabled={offset + queue.limit >= queue.total || busy}
            onClick={() => setOffset(offset + queue.limit)}><ArrowRight size={16} /></button>
        </div>}
      </aside>
      <section className="aw-detail" aria-label="Selected case">
        {caseError && <p className="aw-error" role="alert">{caseError}</p>}
        {activeDetail ? <CasePanel key={activeDetail.case.id} detail={activeDetail} status={status} operation={operation} submit={updateCase} />
          : <div className="aw-card aw-empty" role="status">
            <h2>{selected && !caseError ? "Loading case…" : "No case selected"}</h2>
            <p>{selected && !caseError ? "Retrieving the case record." : "Select a case from the queue to see its details."}</p></div>}
      </section>
    </div>
  </main>;
}

function CasePanel({ detail, status, operation, submit }: {
  detail: Detail; status: Status | null; operation: CaseUpdate["kind"] | null;
  submit: (update: CaseUpdate) => void;
}) {
  const { run, payment, customer, beneficiary, evidence, timeline, verification, watch } = detail;
  const incoming = payment.direction === "incoming";
  const stale = !!run && run.case_version !== detail.case.version;
  const verified = verification.verified_run_id !== null;
  const usedForVerification = verified && verification.verified_run_id === run?.id;
  const busy = operation !== null;
  const [role, setRole] = useState<(typeof roles)[number]["id"]>("reporter");
  const finding = run?.findings[role];
  return <>
    <article className="aw-card aw-case-detail">
      <div className="aw-section-title"><div><p className="aw-kicker">{incoming ? "Incoming money request" : "Outgoing transfer"}</p><h2>{payment.amount_display}</h2>
        <p className="aw-mono aw-muted">{detail.case.id}</p></div>
        <div className="aw-chips"><span className="aw-chip" data-tone={detail.case.severity}>{label(detail.case.severity)}</span>
          <span className="aw-chip">{label(detail.case.state)}</span></div></div>
      <dl className="aw-facts">
        <div><dt>{incoming ? "Receiving customer" : "Sending customer"}</dt><dd>Owner {customer.owner_ref} <small>{customer.account_masked}</small></dd></div>
        <div><dt>{incoming ? "Requested from" : "Recipient"}</dt><dd>{beneficiary.name} <small>{beneficiary.masked}</small></dd></div>
        <div><dt>Policy decision</dt><dd>{label(payment.decision)} <small>{label(payment.state)}</small></dd></div>
        <div><dt>Monitoring</dt><dd>{watch ? label(watch.status) : "No active watch"}<small>{watch ? `${watch.checks} checks` : `${detail.linked_transactions.length} related transfers`}</small></dd></div>
      </dl>
    </article>
    <article className="aw-card aw-record">
      <div className="aw-section-title">
        <h2>Screening</h2>
        <span className="aw-chip" data-tone={detail.suspicion_level === "elevated" ? "medium" : detail.suspicion_level}>
          {detail.suspicion_level} suspicion
        </span>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
        {payment.reasons.map(reason => <li key={reason.code}>{reason.text}</li>)}
      </ul>
    </article>
    {!incoming && payment.state === "VERIFICATION_REQUIRED" && <article className="aw-card aw-record">
      <h2>Transfer verification</h2>
      {verification.delivered_until_ms ? (
        <p className="aw-muted" role="status">Code sent to the customer’s sandbox receipt. It expires at {date(verification.delivered_until_ms)}.</p>
      ) : verification.available ? (
        <form className="aw-review" onSubmit={event => {
          event.preventDefault();
          const rationale = new FormData(event.currentTarget).get("rationale");
          submit({ kind: "send_code", rationale: String(rationale ?? "").trim() });
        }}>
          <p>Approve to send a six-digit code to the customer’s sandbox receipt.</p>
          <label>Approval rationale <textarea name="rationale" required minLength={8} maxLength={1200} rows={2} disabled={busy} /></label>
          <button className="aw-button aw-primary" disabled={busy}>
            {operation === "send_code" ? "Sending code…" : "Approve and send verification code"}
          </button>
        </form>
      ) : <p className="aw-muted">A verification code cannot be issued while a restriction is active.</p>}
    </article>}
    <article className="aw-card aw-analysis">
      <div className="aw-section-title"><div><p className="aw-kicker">Gemini analysis</p><h2>Agent findings</h2></div>
        {(!run || stale) && !usedForVerification && <button className="aw-button aw-primary" disabled={busy || !status || !!status.unavailable_reason}
          onClick={() => submit({ kind: "analysis" })}>{operation === "analysis" ? "Analyzing…" : "Run analysis"}</button>}</div>
      <div className="aw-roles" aria-label="Agent findings">
        {roles.map(({ id, name }) => <button key={id} className="aw-role" aria-pressed={role === id}
          onClick={() => setRole(id)}>{name}{run?.findings[id] && <Check size={13} role="img" aria-label="Complete" />}</button>)}
      </div>
      {operation === "analysis" && <p className="aw-muted" role="status">Running the five agent stages…</p>}
      {operation === "review" && <p className="aw-muted" role="status">Saving review…</p>}
      {status?.unavailable_reason && <p className="aw-muted">{status.unavailable_reason}</p>}
      {stale && !usedForVerification && <p className="aw-warning" role="status">The case changed after this analysis. Evidence links and review are available for current runs.</p>}
      {finding ? <div className="aw-finding">
        <div className="aw-section-title"><h3>{roles.find(item => item.id === role)?.name}</h3>
          <span className="aw-chip">{finding.confidence} confidence</span></div>
        <p>{finding.summary}</p><p><strong>Suggested next step</strong><br />{finding.next_step}</p>
        {!!finding.evidence_refs.length && <div className="aw-chips">{finding.evidence_refs.map(ref => stale
          ? <span className="aw-chip" key={ref}>{ref}</span> : <a className="aw-chip" key={ref} href={"#aw-evidence-" + ref}>{ref}</a>)}</div>}
      </div> : <p className="aw-muted">Run the workflow to generate findings for this case.</p>}
      {run && <p className="aw-run-meta aw-muted">{run.model} · {date(run.created_ms)}{run.traced ? ` · LangSmith run ${run.id}` : ""}</p>}
      {incoming && (verified || payment.state === "VERIFICATION_REQUIRED") && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          {verified ? <p role="status" className="font-semibold text-ok">Verified · Incoming transfer settled</p> : <>
            <p className="aw-muted">{!verification.available ? "This request has a hold or an active restriction."
              : !run || stale ? "Run the current analysis before verifying." : "Verify to settle the incoming transfer."}</p>
            <button className="aw-button aw-primary" disabled={busy || !run || stale || !verification.available}
              onClick={() => { if (run) submit({ kind: "verification", runId: run.id }); }}>
              {operation === "verification" ? "Verifying…" : "Verify it"}
            </button>
          </>}
        </div>
      )}
      {run && !stale && (run.disposition ? <div className="aw-finding"><h3>Analyst review · {label(run.disposition)}</h3><p>{run.note}</p></div>
        : <form className="aw-review" onSubmit={event => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            submit({ kind: "review", runId: run.id, disposition: String(form.get("disposition")), note: String(form.get("note")) });
          }}>
          <h3>Record analyst review</h3>
          <label>Disposition<select name="disposition"><option value="acknowledged">Acknowledged</option><option value="follow_up">Needs follow-up</option></select></label>
          <label>Review note<textarea name="note" required maxLength={1200} rows={2} /></label>
          <button className="aw-button" disabled={busy}>Save review</button>
        </form>)}
    </article>
    <div className="aw-records">
      <article className="aw-card aw-record">
        <div className="aw-section-title"><h2>Evidence</h2><span className="aw-muted">{evidence.length} records</span></div>
        {!evidence.length && <p className="aw-muted">No evidence is attached.</p>}
        {evidence.map((item, index) => <div className="aw-record-row" id={`aw-evidence-E${index + 1}`} key={item.id}>
          <div><strong>{label(item.kind)}</strong><small>E{index + 1} · {label(item.source)}{item.review_only ? " · review only" : ""}</small>
            {item.score !== null && item.score_scale && <small>{item.score} · {item.score_scale}</small>}
          </div>
          <span className="aw-chip" data-tone={item.flagged ? (item.review_only ? "medium" : "high") : undefined}>{label(item.status)}</span>
        </div>)}
      </article>
      <article className="aw-card aw-record">
        <div className="aw-section-title"><h2>Case activity</h2></div>
        {!timeline.length && <p className="aw-muted">No events recorded.</p>}
        {[...timeline].reverse().map(event => <div className="aw-record-row" key={event.id}>
          <div><strong>{label(event.type)}</strong><small>{date(event.created_ms)} · {event.actor}</small></div>
        </div>)}
      </article>
    </div>
  </>;
}
