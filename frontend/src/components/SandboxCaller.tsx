import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Mic, Square, CheckCircle2, Clock } from 'lucide-react';
import { api, customerKey, money, post } from '../sandbox';
import type { Payment, SandboxConfig } from '../sandbox';
import { useCall } from '../hooks/useCall';

const STAGE_LABELS = {
  voice: 'Voice Session',
  transfer: 'Transfer Details',
  status: 'Payment Status',
} as const;

export default function SandboxCaller({ config, onSubmitPayment }: {
  config: SandboxConfig; onSubmitPayment: (caseId?: string) => void;
}) {
  const [key] = useState(customerKey);
  const call = useCall(key);
  const [result, setResult] = useState<Payment>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef({ body: '', key: '' });
  const recording = call.state === 'capturing';
  const preparing = call.state === 'connecting' || call.state === 'processing';
  const [consent, setConsent] = useState(false);
  const [continueToTransfer, setContinueToTransfer] = useState(false);
  const complete = Boolean(call.id) && ['ready', 'insufficient_audio', 'timeout', 'disconnected'].includes(call.state);
  const transfer = complete && (call.state === 'ready' || continueToTransfer);
  const stage = result ? 'status' : transfer ? 'transfer' : 'voice';
  const heading = useRef<HTMLHeadingElement>(null);
  const previousStage = useRef(stage);
  useEffect(() => {
    if (previousStage.current !== stage) heading.current?.focus();
    previousStage.current = stage;
  }, [stage]);

  function startCapture() {
    setContinueToTransfer(false);
    void call.start();
  }

  async function run(operation: () => Promise<Payment>) {
    setError('');
    setBusy(true);
    try {
      const payment = await operation();
      setResult(payment);
      request.current = { body: '', key: '' };
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : 'Request failed.');
    } finally {
      setBusy(false);
    }
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!transfer || busy || !call.id) return;
    const data = new FormData(event.currentTarget);
    const parts = String(data.get('amount')).match(/^(\d+)(?:\.(\d{1,2}))?$/);
    if (!parts) {
      setError('Enter a rupee amount with up to two decimal places.');
      return;
    }
    const body = JSON.stringify({
      amount_minor: Number(parts[1]) * 100 + Number((parts[2] ?? '').padEnd(2, '0')),
      recipient: data.get('recipient'), channel: data.get('channel'),
      narrative: data.get('narrative'), session_id: call.id,
    });
    if (request.current.body !== body) request.current = { body, key: crypto.randomUUID() };
    void run(async () => {
      const payment = await api<Payment>('/payments', key, {
        method: 'POST', body, headers: { 'Idempotency-Key': request.current.key },
      });
      onSubmitPayment(payment.decision === 'ALLOW' ? undefined : payment.payment_id);
      void call.clear();
      return payment;
    });
  }

  const stages = (['voice', 'transfer', 'status'] as const);

  return (
    <div className="mx-auto max-w-2xl animate-entry">

      {/* ── Progress stepper ─────────────────────────────────────────── */}
      <ol
        aria-label="Payment progress"
        className="mb-6 flex gap-1 p-1 rounded-2xl"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        {stages.map((step, index) => {
          const isCurrent = stage === step;
          const isDone = stages.indexOf(stage) > index;
          return (
            <li
              key={step}
              aria-current={isCurrent ? 'step' : undefined}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-all duration-300"
              style={isCurrent ? {
                background: 'rgba(99,102,241,0.15)',
                color: '#a5b4fc',
                boxShadow: '0 0 0 1px rgba(99,102,241,0.25)',
              } : isDone ? {
                color: 'rgba(16,185,129,0.7)',
              } : {
                color: 'rgba(148,163,184,0.4)',
              }}
            >
              <span
                className="flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold"
                style={isDone ? {
                  background: 'rgba(16,185,129,0.15)',
                  color: '#34d399',
                } : isCurrent ? {
                  background: 'rgba(99,102,241,0.3)',
                  color: '#a5b4fc',
                } : {
                  background: 'rgba(255,255,255,0.05)',
                }}
              >
                {isDone ? <CheckCircle2 size={10} /> : index + 1}
              </span>
              <span className="hidden sm:inline">{STAGE_LABELS[step]}</span>
            </li>
          );
        })}
      </ol>

      {/* ── Voice stage ──────────────────────────────────────────────── */}
      {stage === 'voice' && (
        <section className="sandbox-card animate-entry" aria-labelledby="voice-title">
          <div
            className="inline-flex h-10 w-10 items-center justify-center rounded-2xl"
            style={{
              background: recording
                ? 'rgba(244,63,94,0.15)'
                : 'rgba(99,102,241,0.12)',
              border: `1px solid ${recording ? 'rgba(244,63,94,0.3)' : 'rgba(99,102,241,0.25)'}`,
            }}
          >
            <Mic
              size={18}
              aria-hidden="true"
              className={recording ? 'text-red-400' : 'text-indigo-400'}
            />
          </div>

          <div>
            <h2 id="voice-title" ref={heading} tabIndex={-1} className="text-base font-semibold text-slate-100">
              Voice Session
            </h2>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'rgba(148,163,184,0.75)' }}>
              We screen a short voice sample for signs of impersonation before you enter your transfer details.
              Say a few words about the purpose of your transfer. Keep passwords, PINs and verification codes private.
            </p>
          </div>

          {!recording && !preparing && (
            <label className="t-consent-label text-sm" style={{ color: 'rgba(148,163,184,0.85)' }}>
              <input
                className="mt-0.5 h-4 w-4 shrink-0"
                type="checkbox"
                checked={consent}
                onChange={event => setConsent(event.target.checked)}
                style={{ accentColor: '#6366f1' }}
              />
              I consent to microphone access and voice analysis for this payment.
            </label>
          )}

          {/* State message */}
          {({
            connecting: (
              <p role="status" className="flex items-center gap-2 text-sm" style={{ color: 'rgba(148,163,184,0.7)' }}>
                <span className="blink inline-block h-1.5 w-1.5 rounded-full bg-indigo-400" />
                Connecting to your microphone…
              </p>
            ),
            capturing: (
              <p role="status" className="flex items-center gap-2 text-sm text-red-400">
                <span className="blink inline-block h-1.5 w-1.5 rounded-full bg-red-400" />
                Listening. Finish when you have spoken for a few seconds.
              </p>
            ),
            processing: (
              <p role="status" className="flex items-center gap-2 text-sm" style={{ color: 'rgba(148,163,184,0.7)' }}>
                <span className="blink inline-block h-1.5 w-1.5 rounded-full bg-indigo-400" />
                Reviewing your voice sample…
              </p>
            ),
            insufficient_audio: (
              <p role="status" className="text-sm text-amber-400">We did not hear enough speech.</p>
            ),
            disconnected: (
              <p role="status" className="text-sm text-red-400">The voice session was interrupted.</p>
            ),
            timeout: (
              <p role="status" className="text-sm text-amber-400">The voice review timed out.</p>
            ),
          } as Record<string, React.ReactNode>)[call.state]}

          {call.error && (
            <p role="alert" className="text-sm text-red-400">{call.error}</p>
          )}

          <div className="flex flex-wrap gap-2">
            {recording ? (
              <>
                <button className="primary" onClick={() => void call.finish()}>
                  <Square size={14} aria-hidden="true" /> End session
                </button>
                <button className="secondary" onClick={() => void call.clear()}>Cancel</button>
              </>
            ) : (
              <button className="primary" disabled={!consent || preparing} onClick={startCapture}>
                {call.state === 'idle' ? 'Start voice session' : preparing ? 'Please wait…' : 'Try again'}
              </button>
            )}
            {complete && (
              <button className="secondary" onClick={() => setContinueToTransfer(true)}>
                Continue <ArrowRight size={14} aria-hidden="true" />
              </button>
            )}
          </div>
        </section>
      )}

      {/* ── Transfer stage ───────────────────────────────────────────── */}
      {stage === 'transfer' && (
        <form className="sandbox-card animate-entry" onSubmit={submit}>
          <div>
            <h2 ref={heading} tabIndex={-1} className="text-base font-semibold text-slate-100">
              Transfer Details
            </h2>
            <p className="mt-1.5 text-sm" style={{ color: 'rgba(148,163,184,0.7)' }}>
              {call.state === 'ready'
                ? 'Your voice session will be included with this transfer.'
                : 'We could not complete the voice review. Additional verification may be required.'}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="block text-xs font-medium text-slate-500 mb-1.5">Recipient</span>
              <select
                name="recipient"
                defaultValue=""
                required
                className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 focus:border-brand/50 focus:outline-none transition-colors"
                style={{ minHeight: '2.75rem' }}
              >
                <option value="" disabled style={{ background: '#18181f' }}>Select a recipient</option>
                {config.recipients.map(id => (
                  <option key={id} style={{ background: '#18181f' }}>{id}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="block text-xs font-medium text-slate-500 mb-1.5">Amount (₹)</span>
              <input
                name="amount"
                inputMode="decimal"
                pattern="[0-9]+([.][0-9]{1,2})?"
                required
                placeholder="0.00"
                className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-700 focus:border-brand/50 focus:outline-none transition-colors font-mono"
                style={{ minHeight: '2.75rem' }}
              />
            </label>
            <label>
              <span className="block text-xs font-medium text-slate-500 mb-1.5">Payment method</span>
              <select
                name="channel"
                className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 focus:border-brand/50 focus:outline-none transition-colors"
                style={{ minHeight: '2.75rem' }}
              >
                <option style={{ background: '#18181f' }}>UPI</option>
                <option style={{ background: '#18181f' }}>IMPS</option>
                <option style={{ background: '#18181f' }}>WIRE</option>
              </select>
            </label>
          </div>

          <label>
            <span className="block text-xs font-medium text-slate-500 mb-1.5">
              Payment remark <span className="font-normal text-slate-700">(optional)</span>
            </span>
            <textarea
              name="narrative"
              maxLength={1200}
              rows={2}
              placeholder="Brief description of this transfer…"
              className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-700 focus:border-brand/50 focus:outline-none transition-colors resize-none"
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button className="primary" disabled={busy}>Submit transfer</button>
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => { setContinueToTransfer(false); void call.clear(); }}
            >
              Record a new sample
            </button>
            {busy && (
              <span role="status" className="ml-auto flex items-center gap-1.5 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                <span className="blink inline-block h-1.5 w-1.5 rounded-full bg-indigo-500" />
                Submitting…
              </span>
            )}
          </div>
          {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
        </form>
      )}

      {/* ── Status stage ─────────────────────────────────────────────── */}
      {result && (
        <section className="sandbox-card animate-entry" aria-live="polite">
          {/* Outcome indicator */}
          <div className="flex items-center gap-3">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-2xl shrink-0"
              style={result.state === 'SETTLED' ? {
                background: 'rgba(16,185,129,0.12)',
                border: '1px solid rgba(16,185,129,0.25)',
              } : (result.state === 'HELD' || result.state === 'BLOCKED') ? {
                background: 'rgba(244,63,94,0.12)',
                border: '1px solid rgba(244,63,94,0.25)',
              } : {
                background: 'rgba(245,158,11,0.12)',
                border: '1px solid rgba(245,158,11,0.25)',
              }}
            >
              <CheckCircle2
                size={18}
                className={
                  result.state === 'SETTLED' ? 'text-emerald-400' :
                  (result.state === 'HELD' || result.state === 'BLOCKED') ? 'text-red-400' : 'text-amber-400'
                }
              />
            </div>
            <div>
              <h2 ref={heading} tabIndex={-1} className="text-base font-semibold text-slate-100">
                {result.state === 'SETTLED' ? 'Transfer settled' :
                 result.state === 'HELD' ? 'Transfer under review' : result.state === 'BLOCKED' ? 'Transfer blocked' : 'Verification required'}
              </h2>
              <p className="text-sm" style={{ color: 'rgba(148,163,184,0.7)' }}>
                {money(result.amount_minor)} to {result.recipient}
              </p>
            </div>
          </div>

          <p
            className="break-all rounded-xl px-3 py-2 font-mono text-xs"
            style={{ background: 'rgba(255,255,255,0.03)', color: 'rgba(148,163,184,0.5)' }}
          >
            Ref: {result.payment_id}
          </p>

          {result.state === 'STEP_UP_REQUIRED' && (
            <form
              className="space-y-3"
              onSubmit={event => {
                event.preventDefault();
                const code = String(new FormData(event.currentTarget).get('code')).trim();
                void run(() => api('/payments/' + result.payment_id + '/verify', key, post({ code })));
              }}
            >
              <label>
                <span className="block text-xs font-medium text-slate-500 mb-1.5">Verification code</span>
                <input
                  name="code"
                  autoComplete="one-time-code"
                  required
                  maxLength={128}
                  placeholder="Enter the code from the analyst console"
                  className="block w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-slate-100 placeholder:text-slate-700 focus:border-brand/50 focus:outline-none transition-colors font-mono"
                  style={{ minHeight: '2.75rem' }}
                />
              </label>
              <button className="primary" disabled={busy}>Verify transfer</button>
            </form>
          )}

          {error && <p role="alert" className="text-sm text-red-400">{error}</p>}

          <div className="flex flex-wrap gap-2">
            {result.state !== 'SETTLED' && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() => void run(() => api('/payments/' + result.payment_id, key))}
              >
                <Clock size={13} aria-hidden="true" /> Refresh status
              </button>
            )}
            <button
              className="secondary"
              disabled={busy}
              onClick={() => {
                setResult(undefined);
                setError('');
                setConsent(false);
                setContinueToTransfer(false);
                void call.clear();
              }}
            >
              New transfer
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
