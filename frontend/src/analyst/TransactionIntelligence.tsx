import { useEffect, useState, type FormEvent } from "react";
import { ApiError, request } from "../lib/api";
import { formatINR } from "../lib/format";

const endpoint = "/api/v2/analyst/intelligence";
const statuses = ["NEW", "UNDER_REVIEW", "ESCALATED", "RESOLVED", "FALSE_POSITIVE"] as const;
const bands = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
const pageSize = 25;
export const readable = (value: string) => value.toLowerCase().replaceAll("_", " ");
const date = (ms: number) => new Date(ms).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const errorText = (error: unknown) => error instanceof Error ? error.message : "Request failed.";

export type Assessment = {
  payment_id: string; config_version: string; score: number; band: typeof bands[number]; alert: boolean;
  signals: { code: string; points: number; explanation: string; evidence: Record<string, unknown> }[];
  baseline: { settled_samples: number; minimum_samples: number; average_minor: number | null;
    p90_minor: number | null; example_payment_ids: string[] };
  next_action: string;
};
export type AlertLink = { id: string; pattern: string; status: typeof statuses[number]; severity: string };
type Risk = Assessment & { account_id: string; beneficiary: string; amount_minor: number; created_ms: number;
  direction: string; state: string };
type RiskList = { items: Risk[]; summary: { total: number; high: number; critical: number; medium: number; flagged_minor: number } };
type AMLAlert = AlertLink & { recipient_key: string; detected_ms: number; window_start_ms: number; window_end_ms: number;
  evidence: { explanation: string; sender_count: number; transaction_count: number; total_minor: number; bounded: boolean;
    transactions: { payment_id: string; sender_key: string; created_ms: number; amount_minor: number }[] };
  reviews?: { actor: string; new_status: string; note: string; created_ms: number }[];
};
type AMLList = { items: AMLAlert[]; total: number };
type Configuration = { version: string; bands: number[]; weights: number[]; alert_score: number; minimum_history: number;
  history_days: number; aml_days: number; aml_senders: number; aml_transfers: number };

export function RiskEvidence({ assessment }: { assessment: Assessment }) {
  const { score, band, signals, baseline, next_action } = assessment;
  return <section className="aw-card aw-record aw-intel-evidence" aria-label="Transaction risk assessment">
    <div className="aw-section-title"><h3>Transaction risk assessment</h3>
      <span className="aw-chip" data-tone={band.toLowerCase()}>{band}</span></div>
    <div className="aw-risk-score">
      <strong>{score} / 100</strong>
      <meter min={0} max={100} value={score} aria-label="Transaction risk score" />
    </div>
    <p className="aw-muted">Review score · configuration {assessment.config_version}</p>
    {baseline.average_minor === null ? <p>Insufficient settled history ({baseline.settled_samples} of {baseline.minimum_samples} required).</p>
      : <p>{baseline.settled_samples} prior settlements · average {formatINR(baseline.average_minor)} · 90th percentile {formatINR(baseline.p90_minor ?? 0)}</p>}
    {baseline.example_payment_ids.length > 0 && <p className="aw-muted">Sample transfers · {baseline.example_payment_ids.join(", ")}</p>}
    {signals.length ? <ul className="aw-intel-signals">{signals.map(signal => <li key={signal.code}>
      <div className="aw-section-title"><strong>{readable(signal.code)}</strong><span>+{signal.points}</span></div>
      <p>{signal.explanation}</p>
      <details><summary>Supporting evidence</summary><dl>
        {Object.entries(signal.evidence).map(([key, value]) => <div key={key}>
          <dt>{readable(key.replace(/_minor$/, ""))}</dt>
          <dd>{key.endsWith("_minor") && typeof value === "number" ? formatINR(value) :
            key === "windows" && Array.isArray(value) ? value.map(window =>
              `${window.window_minutes} min: ${window.count} submissions, limit ${window.threshold}`).join(" · ") : String(value)}</dd>
        </div>)}
      </dl></details>
    </li>)}</ul> : <p>No risk rules fired.</p>}
    <p><strong>Suggested analyst action</strong> · {next_action}</p>
  </section>;
}

export function TransactionIntelligence({ token, page, alertId, onAuthFailure }: {
  token: string; page: "risk" | "aml" | "config"; alertId: string | null; onAuthFailure: () => void;
}) {
  const [band, setBand] = useState("");
  const [status, setStatus] = useState("");
  const [account, setAccount] = useState("");
  const [beneficiary, setBeneficiary] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [minimum, setMinimum] = useState("");
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selectedRisk, setSelectedRisk] = useState<Risk | null>(null);
  const [selectedAlert, setSelectedAlert] = useState(alertId);
  const [detail, setDetail] = useState<AMLAlert | null>(null);
  const [result, setResult] = useState<RiskList | AMLList | Configuration | null>(null);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    const query = new URLSearchParams({ offset: String(offset), limit: String(pageSize) });
    if (page === "risk") {
      if (band) query.set("band", band);
      if (account.trim()) query.set("account_id", account.trim());
      if (beneficiary.trim()) query.set("beneficiary", beneficiary.trim());
      if (from) query.set("from_ms", String(new Date(from + "T00:00:00").getTime()));
      if (to) query.set("to_ms", String(new Date(to + "T23:59:59.999").getTime()));
      if (minimum) query.set("min_amount_minor", String(Math.round(Number(minimum) * 100)));
      if (alertsOnly) query.set("alerts_only", "true");
    } else if (status) query.set("status", status);
    setResult(null);
    setSelectedRisk(null);
    setError("");
    request<RiskList | AMLList | Configuration>(endpoint + "/" + page + (page === "config" ? "" : "?" + query),
      { token, signal: ctrl.signal }).then(data => { if (!ctrl.signal.aborted) setResult(data); })
      .catch(err => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) onAuthFailure();
        else setError(errorText(err));
      });
    return () => ctrl.abort();
  }, [token, page, band, account, beneficiary, from, to, minimum, alertsOnly, status, offset, revision, onAuthFailure]);

  useEffect(() => {
    setDetail(null);
    setDetailError("");
    if (!selectedAlert) return;
    const ctrl = new AbortController();
    request<AMLAlert>(endpoint + "/aml/" + encodeURIComponent(selectedAlert), { token, signal: ctrl.signal })
      .then(data => { if (!ctrl.signal.aborted) setDetail(data); })
      .catch(err => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) onAuthFailure();
        else setDetailError(errorText(err));
      });
    return () => ctrl.abort();
  }, [token, selectedAlert, revision, onAuthFailure]);

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail) return;
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setDetailError("");
    setSaved("");
    try {
      await request(endpoint + "/aml/" + encodeURIComponent(detail.id) + "/review", { token, method: "POST",
        body: { status: form.get("status"), expected_status: detail.status, note: form.get("note") } });
      setSaved("Review saved.");
      setRevision(value => value + 1);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onAuthFailure();
      else setDetailError(errorText(err));
    } finally { setSaving(false); }
  }

  const risk = result && "summary" in result ? result : null;
  const aml = result && "items" in result && !("summary" in result) ? result : null;
  const config = result && "version" in result ? result : null;
  const total = risk?.summary.total ?? aml?.total ?? 0;
  return <main className="aw-main aw-intelligence">
    <h1>{page === "risk" ? "Transaction Risk Monitor" : page === "aml" ? "AML Monitoring" : "Risk Configuration"}</h1>
    {page === "risk" && <fieldset className="aw-filters aw-card">
      <legend className="sr-only">Risk filters</legend>
      <label>Risk band<select value={band} onChange={e => { setBand(e.target.value); setOffset(0); }}>
        <option value="">All bands</option>{bands.map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label>Account ID<input value={account} maxLength={80} onChange={e => { setAccount(e.target.value); setOffset(0); }} /></label>
      <label>Contact<input value={beneficiary} maxLength={80} onChange={e => { setBeneficiary(e.target.value); setOffset(0); }} /></label>
      <label>From<input type="date" value={from} max={to || undefined} onChange={e => { setFrom(e.target.value); setOffset(0); }} /></label>
      <label>Through<input type="date" value={to} min={from || undefined} onChange={e => { setTo(e.target.value); setOffset(0); }} /></label>
      <label>Minimum amount (₹)<input type="number" min={0} max={100000000} step="0.01" value={minimum}
        onChange={e => { setMinimum(e.target.value); setOffset(0); }} /></label>
      <label><input type="checkbox" checked={alertsOnly} onChange={e => { setAlertsOnly(e.target.checked); setOffset(0); }} /> Flagged only</label>
    </fieldset>}
    {page === "aml" && <fieldset className="aw-filters aw-card">
      <legend className="sr-only">AML filters</legend>
      <label>Investigation status<select value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}>
        <option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{readable(value)}</option>)}
      </select></label>
    </fieldset>}
    {error && <p className="aw-error" role="alert">{error}</p>}
    {!result && !error && <p role="status">Loading intelligence…</p>}
    {risk && <>
      <dl className="aw-facts aw-card aw-record">
        <div><dt>Assessed</dt><dd>{risk.summary.total}</dd></div>
        <div><dt>Medium / High / Critical</dt><dd>{risk.summary.medium} / {risk.summary.high} / {risk.summary.critical}</dd></div>
        <div><dt>Flagged transfer value</dt><dd>{formatINR(risk.summary.flagged_minor)}</dd></div>
      </dl>
      <div className="aw-card aw-intel-table"><table>
        <caption className="sr-only">Transaction risk results</caption>
        <thead><tr><th>Payment</th><th>Account</th><th>Contact</th><th>Amount</th><th>Submitted</th><th>Risk</th><th>Signals</th><th>State</th></tr></thead>
        <tbody>{risk.items.map(item => <tr key={item.payment_id}>
          <td><button className="aw-intel-link" onClick={() => setSelectedRisk(item)}>{item.payment_id}</button></td>
          <td>{item.account_id}</td><td>{item.beneficiary}</td><td>{formatINR(item.amount_minor)}</td><td>{date(item.created_ms)}</td>
          <td>{item.score} · {item.band}</td><td>{item.signals.length}</td><td>{readable(item.state)}</td>
        </tr>)}</tbody>
      </table>{!risk.items.length && <p className="aw-record">No matching risk assessments.</p>}</div>
      {selectedRisk && <div>
        <div className="aw-section-title"><h2>{selectedRisk.payment_id}</h2>
          <button className="aw-button" onClick={() => setSelectedRisk(null)}>Close details</button></div>
        <p>{formatINR(selectedRisk.amount_minor)} · {selectedRisk.direction} · {selectedRisk.beneficiary}</p>
        <RiskEvidence assessment={selectedRisk} />
      </div>}
    </>}
    {aml && <>
      <p>{aml.total} matching AML alerts</p>
      <div className="aw-card aw-intel-table"><table>
        <caption className="sr-only">AML alerts</caption>
        <thead><tr><th>Alert</th><th>Pattern</th><th>Recipient</th><th>Severity</th><th>Status</th><th>Detected</th></tr></thead>
        <tbody>{aml.items.map(item => <tr key={item.id}>
          <td><button className="aw-intel-link" onClick={() => { setSaved(""); setSelectedAlert(item.id); }}>{item.id}</button></td>
          <td>{readable(item.pattern)}</td><td>{item.recipient_key}</td><td>{readable(item.severity)}</td>
          <td>{readable(item.status)}</td><td>{date(item.detected_ms)}</td>
        </tr>)}</tbody>
      </table>{!aml.items.length && <p className="aw-record">No matching AML alerts.</p>}</div>
    </>}
    {total > pageSize && <div className="aw-pagination">
      <button className="aw-button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
      <span>{offset + 1}–{Math.min(total, offset + pageSize)} of {total}</span>
      <button className="aw-button" disabled={offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)}>Next</button>
    </div>}
    {saved && <p role="status">{saved}</p>}
    {detailError && <p className="aw-error" role="alert">{detailError}</p>}
    {selectedAlert && !detail && !detailError && <p role="status">Loading alert…</p>}
    {detail && <section className="aw-card aw-record aw-intel-evidence" aria-label="AML alert details">
      <div className="aw-section-title"><h2>{readable(detail.pattern)}</h2><span className="aw-chip">{readable(detail.status)}</span></div>
      <p>{detail.evidence.explanation}</p>
      <p>{date(detail.window_start_ms)} to {date(detail.window_end_ms)}</p>
      <dl className="aw-facts">
        <div><dt>Distinct senders</dt><dd>{detail.evidence.sender_count}</dd></div>
        <div><dt>Settled transfers</dt><dd>{detail.evidence.transaction_count}</dd></div>
        <div><dt>Total settled value</dt><dd>{formatINR(detail.evidence.total_minor)}</dd></div>
      </dl>
      {detail.evidence.bounded && <p className="aw-muted">Evidence uses a bounded sample of recent settlements.</p>}
      <details><summary>Supporting transfers</summary><div className="aw-intel-table"><table>
        <thead><tr><th>Payment</th><th>Sender</th><th>Amount</th><th>Settled</th></tr></thead>
        <tbody>{detail.evidence.transactions.map(row => <tr key={row.payment_id}>
          <td>{row.payment_id}</td><td>{row.sender_key}</td><td>{formatINR(row.amount_minor)}</td><td>{date(row.created_ms)}</td>
        </tr>)}</tbody>
      </table></div></details>
      <form key={detail.id + detail.status} className="aw-review" onSubmit={review}>
        <label>Set investigation status<select name="status" required defaultValue="">
          <option value="" disabled>Select status</option>
          {statuses.slice(1).filter(value => value !== detail.status).map(value => <option key={value} value={value}>{readable(value)}</option>)}
        </select></label>
        <label>Review note<textarea name="note" required maxLength={1200} rows={2} /></label>
        <button className="aw-button aw-primary" disabled={saving}>{saving ? "Saving…" : "Save AML review"}</button>
      </form>
      {!!detail.reviews?.length && <details><summary>Review history</summary><ul>{detail.reviews.map((item, index) =>
        <li key={index}>{date(item.created_ms)} · {item.actor} · {readable(item.new_status)} · {item.note}</li>)}</ul></details>}
    </section>}
    {config && <section className="aw-card aw-record aw-intel-evidence">
      <h2>Sandbox rules · {config.version}</h2>
      <p>Scores help prioritize analyst review. Payment decisions use the gateway policy.</p>
      <p>Medium / High / Critical start at {config.bands.join(" / ")}. Flagged at {config.alert_score}.</p>
      <p>Baselines use up to {config.history_days} days of settled history and require {config.minimum_history} samples.</p>
      <dl className="aw-intel-signals">{["Unusually large transaction", "New beneficiary and high value", "Unusual frequency",
        "Unusual timing", "Outgoing surge", "Previously flagged entity"].map((name, index) =>
        <div key={name}><dt>{name}</dt><dd>{config.weights[index]} points</dd></div>)}</dl>
      <p>Common-beneficiary alerts require {config.aml_senders} distinct senders and {config.aml_transfers} settled transfers within {config.aml_days} days.</p>
    </section>}
  </main>;
}
