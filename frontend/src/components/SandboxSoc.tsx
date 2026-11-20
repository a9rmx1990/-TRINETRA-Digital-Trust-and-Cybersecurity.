import { useEffect, useRef, useState } from 'react';
import { api, caseSocket, money, post } from '../sandbox';
import type { Case, CasePage, SocOverview } from '../sandbox';
import GraphPanel from './GraphPanel';
import AgentCase from './AgentCase';
import { Lock, Radio, TrendingUp } from 'lucide-react';

const dateLabel = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
const providerLabel: Record<string, string> = {
  disabled: 'Automatic AI enrichment is off', not_configured: 'AI provider is unconfigured',
  unreachable: 'AI provider was unreachable', timeout: 'AI provider timed out',
  invalid_response: 'AI response could not be read',
};

/* ── Stat card ─────────────────────────────────────────────────────────── */
function StatCard({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return (
    <div
      className="rounded-xl p-3 flex flex-col gap-1"
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.07)',
      }}
    >
      <dt className="text-xs font-medium" style={{ color: 'rgba(148,163,184,0.6)' }}>{label}</dt>
      <dd
        className="text-xl font-bold tabular-nums tracking-tight"
        style={{ color: accent ?? '#e2e8f0' }}
      >
        {value}
      </dd>
    </div>
  );
}

/* ── Activity overview ─────────────────────────────────────────────────── */
function ActivityOverview({ overview }: { overview: SocOverview }) {
  const stats: Array<[string, number, string?]> = [
    ['Transfers', overview.payments],
    ['Sessions', overview.sessions],
    ['Flagged', overview.flagged, overview.flagged > 0 ? '#fb7185' : undefined],
    ['Open cases', overview.open, overview.open > 0 ? '#fbbf24' : undefined],
    ['Investigated', overview.investigated, '#34d399'],
    ['AI assessed', overview.ai_assessed, '#a5b4fc'],
  ];
  const max = Math.max(1, ...overview.daily.map(day => day.payments));

  return (
    <section className="sandbox-card animate-entry" aria-labelledby="activity-heading">
      <div className="flex items-center justify-between">
        <div>
          <h2 id="activity-heading" className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <TrendingUp size={14} className="text-indigo-400" />
            Activity Overview
          </h2>
          <p className="mt-0.5 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>Last 7 calendar days · UTC</p>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        {stats.map(([label, value, accent]) => (
          <StatCard key={label} label={label} value={value} accent={accent} />
        ))}
      </dl>

      {/* Mini bar chart */}
      <div>
        <div className="mb-2 flex items-center justify-between text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
          <span>Daily transfer volume</span>
          <span>Flagged</span>
        </div>
        <div className="space-y-1">
          {overview.daily.map(day => (
            <div key={day.day} className="flex items-center gap-3 text-xs">
              <span className="w-12 shrink-0 font-mono" style={{ color: 'rgba(148,163,184,0.5)' }}>
                {dateLabel.format(day.day * 1000)}
              </span>
              <div className="flex flex-1 items-center gap-1.5 tabular-nums">
                <span className="w-6 text-right" style={{ color: 'rgba(148,163,184,0.7)' }}>{day.payments}</span>
                <span
                  className="h-1.5 rounded-full transition-all"
                  aria-hidden="true"
                  style={{
                    width: (day.payments / max * 100) + '%',
                    background: 'rgba(99,102,241,0.6)',
                  }}
                />
              </div>
              <span
                className="w-6 text-right font-mono"
                style={{ color: day.flagged > 0 ? '#fb7185' : 'rgba(148,163,184,0.4)' }}
              >
                {day.flagged}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Main component ────────────────────────────────────────────────────── */
export default function SandboxSoc({ enabled, analystKey, onKey, preferredCaseId }: {
  enabled: boolean; analystKey: string; onKey: (key: string) => void; preferredCaseId?: string;
}) {
  const [cases, setCases] = useState<CasePage['cases']>([]);
  const [recent, setRecent] = useState<CasePage['recent']>([]);
  const [selected, setSelected] = useState<Case>();
  const [overview, setOverview] = useState<SocOverview>();
  const currentCase = useRef<string | undefined>(undefined);
  const [data, setData] = useState<unknown>();
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!analystKey) return;
    let cursor = 0;
    let live = true;
    let refreshing = false;
    let socket: WebSocket | undefined;
    let retry: number | undefined;
    async function refresh() {
      if (refreshing || !live) return;
      refreshing = true;
      try {
        const result = await api<CasePage>('/cases?after=' + cursor + '&include_closed=true', analystKey);
        if (live) {
          setCases(result.cases);
          setRecent(result.recent);
          setOverview(result.overview);
          const current = currentCase.current;
          const id = current ?? preferredCaseId ?? result.recent.find(payment => payment.has_case)?.payment_id
            ?? result.cases[0]?.payment_id;
          if (id && (!current || result.updated_ids.includes(id))) {
            const item = await api<Case>('/cases/' + id, analystKey);
            if (live && currentCase.current === current) {
              currentCase.current = id;
              setSelected(item);
            }
          }
          cursor = result.cursor;
        }
      } catch (ex) {
        if (live) setError(ex instanceof Error ? ex.message : 'Could not load cases.');
      } finally {
        refreshing = false;
      }
    }
    function connect() {
      socket = caseSocket();
      socket.onopen = () => socket?.send(JSON.stringify({ key: analystKey, after: cursor }));
      socket.onmessage = () => {
        if (!live) return;
        setConnected(true);
        void refresh();
      };
      socket.onclose = ({ code }) => {
        if (!live) return;
        setConnected(false);
        if (code !== 1008) retry = window.setTimeout(connect, 2500);
      };
    }
    void refresh();
    connect();
    const timer = window.setInterval(refresh, 4000);
    return () => {
      live = false;
      clearInterval(timer);
      clearTimeout(retry);
      if (socket?.readyState === WebSocket.OPEN) socket.close();
      else if (socket?.readyState === WebSocket.CONNECTING) socket.onopen = () => socket?.close();
    };
  }, [analystKey, preferredCaseId]);

  async function run(operation: () => Promise<void>) {
    setError('');
    setBusy(true);
    try { await operation(); } catch (ex) {
      setError(ex instanceof Error ? ex.message : 'Analyst action failed.');
    } finally { setBusy(false); }
  }

  async function open(id: string) {
    setSelected(await api('/cases/' + id, analystKey));
    currentCase.current = id;
    setData(undefined);
    setCode('');
  }

  /* ── Auth gate ─────────────────────────────────────────────────────── */
  if (!analystKey) {
    return (
      <form
        className="sandbox-card mx-auto max-w-md animate-entry space-y-4"
        onSubmit={event => {
          event.preventDefault();
          onKey(String(new FormData(event.currentTarget).get('key')).trim());
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-2xl"
            style={{
              background: 'rgba(99,102,241,0.12)',
              border: '1px solid rgba(99,102,241,0.25)',
            }}
          >
            <Lock size={16} className="text-indigo-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-100">Analyst Access</h2>
            <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>Security Operations Console</p>
          </div>
        </div>

        {enabled ? (
          <>
            <label>
              <span className="block text-xs font-medium text-slate-500 mb-1.5">Analyst key</span>
              <input
                name="key"
                type="password"
                required
                placeholder="Enter your analyst key"
                className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-700 focus:border-brand/50 focus:outline-none transition-colors font-mono"
                style={{ minHeight: '2.75rem' }}
              />
            </label>
            <button className="primary w-full">Open case queue</button>
          </>
        ) : (
          <p className="text-sm" style={{ color: 'rgba(148,163,184,0.6)' }}>
            Set <code className="font-mono text-indigo-400">TRINETRA_ANALYST_KEY</code> on the backend to enable sandbox analyst access.
          </p>
        )}
      </form>
    );
  }

  const call = selected?.evidence.call;
  const graph = selected?.evidence.graph;
  const assessment = selected?.triage;
  const history = assessment?.history;
  const providerStatus = assessment?.provider_status;
  const providerMessage = providerStatus?.startsWith('http_')
    ? 'AI provider returned HTTP ' + providerStatus.slice(5)
    : providerLabel[providerStatus ?? ''];
  const voiceLabel = selected?.voice_verdict === 'likely_genuine' ? 'Likely genuine' :
    selected?.voice_verdict === 'suspected_synthetic' ? 'Suspected synthetic' : 'Inconclusive';

  return (
    <div className="space-y-5 animate-entry">

      {/* ── Status bar ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: connected ? '#34d399' : 'rgba(148,163,184,0.4)' }}
          />
          {connected ? (
            <span className="flex items-center gap-1.5">
              <Radio size={11} className="text-emerald-400" />
              Receiving live updates
            </span>
          ) : 'Polling for updates'}
        </div>
        <button
          className="secondary text-xs"
          onClick={() => {
            currentCase.current = undefined;
            onKey('');
            setCases([]);
            setRecent([]);
            setOverview(undefined);
            setSelected(undefined);
            setError('');
            setConnected(false);
          }}
        >
          <Lock size={12} aria-hidden="true" /> Lock console
        </button>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-xl p-3 text-sm"
          style={{ background: 'rgba(244,63,94,0.08)', border: '1px solid rgba(244,63,94,0.2)', color: '#fda4af' }}
        >
          {error}
        </p>
      )}

      {overview && <ActivityOverview overview={overview} />}

      {/* ── Case grid ──────────────────────────────────────────────── */}
      <div className="grid gap-5 lg:grid-cols-[1fr_1.45fr]">

        {/* Case queue */}
        <section className="sandbox-card space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Case Queue</h2>
            <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>Ordered by review priority</p>
          </div>

          {cases.length === 0 && (
            <p className="text-sm" style={{ color: 'rgba(148,163,184,0.4)' }}>No cases yet.</p>
          )}

          <div className="space-y-1.5">
            {cases.map(item => (
              <button
                key={item.payment_id}
                className="case-row"
                aria-pressed={selected?.payment_id === item.payment_id}
                disabled={busy}
                onClick={() => void run(() => open(item.payment_id))}
              >
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-200 truncate">{item.recipient}</span>
                  <span className="block text-xs font-mono" style={{ color: 'rgba(148,163,184,0.6)' }}>
                    {money(item.amount_minor)} · {item.payment_id.slice(0, 8)}
                  </span>
                </span>
                <span
                  className="shrink-0 rounded-lg px-2 py-0.5 text-xs font-semibold"
                  style={item.state === 'HELD' || item.state === 'BLOCKED' ? {
                    background: 'rgba(244,63,94,0.12)',
                    color: '#fb7185',
                    border: '1px solid rgba(244,63,94,0.2)',
                  } : {
                    background: 'rgba(245,158,11,0.12)',
                    color: '#fbbf24',
                    border: '1px solid rgba(245,158,11,0.2)',
                  }}
                >
                  {item.case_status === 'OPEN' ? (item.state === 'STEP_UP_REQUIRED' ? 'STEP-UP' : item.state) : item.case_status}
                  {' · '}{item.risk_score.toFixed(0)}
                </span>
              </button>
            ))}
          </div>

          {/* Recent payments */}
          {recent.length > 0 && (
            <div
              className="border-t pt-3 space-y-2"
              style={{ borderColor: 'rgba(255,255,255,0.06)' }}
            >
              <h3 className="text-xs font-semibold text-slate-400">Recent Payments</h3>
              <ul className="space-y-2 text-xs">
                {recent.map(payment => (
                  <li
                    key={payment.payment_id}
                    className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1"
                    style={{ color: 'rgba(148,163,184,0.7)' }}
                  >
                    <span>
                      <span className="text-slate-300">{payment.recipient}</span>
                      {' · '}{money(payment.amount_minor)}
                      <span className="block font-mono" style={{ color: 'rgba(148,163,184,0.4)' }}>
                        {payment.payment_id.slice(0, 8)}
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span>{payment.state.replace(/_/g, ' ')}</span>
                      {payment.has_case && (
                        <button
                          className="secondary text-xs"
                          disabled={busy}
                          aria-label={'Open case ' + payment.payment_id.slice(0, 8)}
                          onClick={() => void run(() => open(payment.payment_id))}
                        >
                          Open
                        </button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {/* Evidence panel */}
        {selected && graph && (
          <section className="sandbox-card min-w-0 space-y-5" aria-busy={busy}>

            {/* Case header */}
            <div>
              <h2 className="text-sm font-semibold text-slate-200">Case Evidence</h2>
              <p className="mt-1 text-sm font-medium text-slate-300">
                {money(selected.amount_minor)} → {selected.recipient}
              </p>
              <p
                className="mt-0.5 break-all font-mono text-xs"
                style={{ color: 'rgba(148,163,184,0.4)' }}
              >
                {selected.payment_id}
              </p>
              <p className="mt-1 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                {selected.state} · {selected.policy_version}
              </p>
            </div>

            {/* AI assessment */}
            {assessment && (
              <div
                className="rounded-xl p-4 space-y-2 text-sm"
                style={{
                  background: 'rgba(99,102,241,0.06)',
                  border: '1px solid rgba(99,102,241,0.15)',
                }}
              >
                <h3 className="font-semibold text-indigo-300 text-xs uppercase tracking-wider">
                  {assessment.source === 'copilot' ? 'AI Assessment' : 'Automated Assessment'}
                </h3>
                {!assessment.investigated_at && (
                  <p role="status" className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                    Investigation queued.
                  </p>
                )}
                {providerMessage && (
                  <p className="text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
                    {providerMessage}. Showing local findings.
                  </p>
                )}
                <p className="whitespace-pre-wrap leading-relaxed text-slate-300">{assessment.summary}</p>
                <p className="text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>
                  <span className="font-semibold text-slate-400">Recommended: </span>
                  {assessment.recommendation}
                </p>
                {assessment.references.window && (
                  <p className="break-all text-xs font-mono" style={{ color: 'rgba(148,163,184,0.4)' }}>
                    Audio: {assessment.references.window}
                  </p>
                )}
                {assessment.references.path.length > 0 && (
                  <p className="break-all text-xs font-mono" style={{ color: 'rgba(148,163,184,0.4)' }}>
                    Graph: {assessment.references.path.join(', ')}
                  </p>
                )}
              </div>
            )}

            {/* Related activity */}
            {history && (
              <div
                className="rounded-xl p-4 space-y-3 text-sm"
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.07)',
                }}
              >
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Related Activity · {history.lookback_days}d lookback
                </h3>
                <dl className="grid gap-2 sm:grid-cols-2 text-xs">
                  <div>
                    <dt className="text-slate-500">Same caller session</dt>
                    <dd className="text-slate-300 font-medium">{history.session_payments} transfers · {history.session_flagged} flagged</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Same recipient</dt>
                    <dd className="text-slate-300 font-medium">{history.recipient_payments} transfers · {history.recipient_flagged} flagged</dd>
                  </div>
                </dl>
                <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                  {history.other_session_recipient_flagged} flagged transfers to this recipient from other sessions.
                </p>
                {history.related_cases.length > 0 && (
                  <ul className="space-y-1">
                    {history.related_cases.map(item => (
                      <li key={item.payment_id}>
                        <button
                          className="secondary max-w-full break-all text-xs"
                          disabled={busy}
                          onClick={() => void run(() => open(item.payment_id))}
                        >
                          {dateLabel.format(item.created * 1000)} ·{' '}
                          {item.same_session && item.same_recipient ? 'Same session and recipient' :
                           item.same_session ? 'Same session' : 'Same recipient'}{' '}
                          · {item.payment_id.slice(0, 8)}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* Voice screening */}
            <div className="text-sm space-y-2">
              <p>
                <span className="font-semibold text-slate-300">Voice screening</span>
                <span style={{ color: 'rgba(148,163,184,0.6)' }}> · {voiceLabel}</span>
              </p>
              <ul className="space-y-1 pl-4 text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>
                {selected.reasons.map(reason => (
                  <li key={reason} className="flex items-start gap-1.5">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-indigo-500" />
                    {reason}
                  </li>
                ))}
              </ul>
            </div>

            {/* Call evidence */}
            {call && (
              <div className="space-y-2 text-sm">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Voice Evidence · {call.transport}
                </h3>
                <p className="text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
                  DSP {call.acoustic.baseline.score} · Spoof {call.acoustic.spoof.status} · ASR {call.coercion.asr.status}
                </p>
                {/* Spectrum bars */}
                <div
                  className="flex h-14 items-end gap-px rounded-xl overflow-hidden p-2"
                  role="img"
                  aria-label="Measured audio frequency bands in decibels"
                  style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
                >
                  {call.acoustic.baseline.spectrum_db.map((db, i) => (
                    <span
                      key={i}
                      className="flex-1 rounded-sm transition-all"
                      style={{
                        height: Math.max(3, (80 + db) * 1.25) + '%',
                        background: `rgba(99,102,241,${0.4 + Math.min(0.5, (80 + db) / 160)})`,
                      }}
                    />
                  ))}
                </div>
                {call.coercion.asr.text && (
                  <blockquote
                    className="rounded-r-xl pl-3 py-2 pr-3 text-xs italic"
                    style={{
                      borderLeft: '2px solid rgba(99,102,241,0.5)',
                      background: 'rgba(99,102,241,0.06)',
                      color: 'rgba(148,163,184,0.8)',
                    }}
                  >
                    {call.coercion.asr.text}
                  </blockquote>
                )}
              </div>
            )}

            {/* Graph */}
            <GraphPanel latestGraph={graph} fetchInitial={false} />
            {graph.truncated && (
              <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                Graph evidence reached its search bounds.
              </p>
            )}

            {/* Evidence actions */}
            <div className="flex flex-wrap gap-2">
              <button
                className="secondary text-xs"
                disabled={busy}
                onClick={() => void run(async () => {
                  await api('/cases/' + selected.payment_id + '/summary', analystKey, post());
                  await open(selected.payment_id);
                })}
              >
                Refresh assessment
              </button>
              {(['downstream', 'cycle', 'voice', 'transcript'] as const).map(intent => (
                <button
                  key={intent}
                  className="secondary capitalize text-xs"
                  disabled={busy}
                  onClick={() => void run(async () => {
                    const result = await api<{ evidence: unknown }>(
                      '/cases/' + selected.payment_id + '/evidence?intent=' + intent, analystKey
                    );
                    setData(result.evidence);
                  })}
                >
                  {intent}
                </button>
              ))}
            </div>

            {/* Ask a question */}
            <form
              className="space-y-2"
              onSubmit={event => {
                event.preventDefault();
                const question = String(new FormData(event.currentTarget).get('question'));
                void run(async () => {
                  const answer = await api<{ evidence: unknown }>(
                    '/cases/' + selected.payment_id + '/question', analystKey, post({ question })
                  );
                  setData(answer.evidence);
                });
              }}
            >
              <label>
                <span className="block text-xs font-medium text-slate-500 mb-1.5">Ask about this case</span>
                <input
                  name="question"
                  placeholder="Which accounts are linked downstream?"
                  maxLength={300}
                  required
                  className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-700 focus:border-brand/50 focus:outline-none transition-colors"
                  style={{ minHeight: '2.75rem' }}
                />
              </label>
              <button className="secondary text-xs" disabled={busy}>Find evidence</button>
            </form>

            {/* Evidence output */}
            {data !== undefined && (
              <pre
                className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-xl p-3 text-xs font-mono leading-relaxed"
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.07)',
                  color: 'rgba(148,163,184,0.8)',
                }}
              >
                {JSON.stringify(data, null, 2)}
              </pre>
            )}

            <AgentCase key={selected.payment_id} item={selected} busy={busy}
              review={(id, decision, note) => void run(async () => {
                await api('/cases/' + selected.payment_id + '/agent/proposals/' + encodeURIComponent(id),
                  analystKey, post({ decision, note }));
                await open(selected.payment_id);
              })}
              override={(verdict, note) => void run(async () => {
                await api('/cases/' + selected.payment_id + '/agent/override', analystKey,
                  post({ version: selected.version, verdict, note }));
                await open(selected.payment_id);
              })}
              toggle={kill_switch => void run(async () => {
                await api('/soc/controls', analystKey, post({ kill_switch }));
                await open(selected.payment_id);
              })}
              revealChallenge={() => void run(async () => {
                const response = await api<{ challenge_code: string }>(
                  '/cases/' + selected.payment_id + '/agent/challenge', analystKey);
                setCode(response.challenge_code);
              })}
            />

            {/* Case actions */}
            {selected.case_status === 'OPEN' && (selected.state === 'HELD' || selected.state === 'STEP_UP_REQUIRED') && (
              <form
                className="space-y-3"
                onSubmit={event => {
                  event.preventDefault();
                  const action = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value');
                  const note = String(new FormData(event.currentTarget).get('note')).trim();
                  if (!action) return;
                  void run(async () => {
                    const response = await api<{ challenge_code: string | null }>(
                      '/cases/' + selected.payment_id + '/action', analystKey,
                      post({ action, version: selected.version, note })
                    );
                    await open(selected.payment_id);
                    setCode(response.challenge_code ?? '');
                  });
                }}
              >
                <label>
                  <span className="block text-xs font-medium text-slate-500 mb-1.5">Analyst rationale</span>
                  <input
                    name="note"
                    minLength={3}
                    maxLength={500}
                    required
                    placeholder="Document your reasoning…"
                    className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-700 focus:border-brand/50 focus:outline-none transition-colors"
                    style={{ minHeight: '2.75rem' }}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  {selected.state === 'STEP_UP_REQUIRED' ? (
                    <button className="primary" disabled={busy} value="ISSUE_CHALLENGE">
                      Issue verification code
                    </button>
                  ) : (
                    <>
                      <button className="secondary" disabled={busy} value="RELEASE">
                        Release held payment
                      </button>
                      <button className="primary" disabled={busy} value="CONFIRM_FREEZE">
                        Confirm account freeze
                      </button>
                    </>
                  )}
                </div>
              </form>
            )}

            {/* Challenge code */}
            {code && (
              <p
                role="status"
                className="break-all rounded-xl p-3 text-sm"
                style={{
                  background: 'rgba(99,102,241,0.08)',
                  border: '1px solid rgba(99,102,241,0.2)',
                  color: '#a5b4fc',
                }}
              >
                Verification code: <strong className="font-mono text-white">{code}</strong>
              </p>
            )}

            {/* Audit log */}
            <ol className="space-y-1 text-xs" style={{ color: 'rgba(148,163,184,0.45)' }}>
              {selected.events?.map(item => (
                <li key={item.seq} className="flex items-start gap-2">
                  <span className="mt-0.5 h-1 w-1 shrink-0 rounded-full bg-slate-700" />
                  {new Date(item.time * 1000).toLocaleString()} · {item.kind}
                  {item.detail.note ? ' · ' + item.detail.note : ''}
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </div>
  );
}
