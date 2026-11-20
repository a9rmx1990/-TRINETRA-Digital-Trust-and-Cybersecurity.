/**
 * TransferForm — Retail banking transfer UI (OLED dark)
 */
import { useState } from 'react';
import { ArrowRightLeft, Send } from 'lucide-react';
import { intercept } from '../api';
import type { InterceptionResponse, Channel } from '../types';
import VoiceAuthWidget from './VoiceAuthWidget';
import OutcomeBanner from './OutcomeBanner';

const CHANNELS: Channel[] = ['UPI', 'IMPS', 'WIRE', 'NEFT', 'RTGS', 'CARD'];

interface FormState {
  sender_account: string;
  recipient_account: string;
  amount: string;
  channel: Channel;
  recipient_account_age_days: string;
  narrative_context: string;
}

const DEFAULT: FormState = {
  sender_account: 'ACC-1001',
  recipient_account: 'ACC-2002',
  amount: '4500',
  channel: 'UPI',
  recipient_account_age_days: '365',
  narrative_context: 'Monthly utility bill payment',
};

const INPUT_CLASS = `
  w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-slate-200
  placeholder:text-slate-700 focus:border-indigo-500/50 focus:outline-none transition-colors
`.trim();

export default function TransferForm() {
  const [form, setForm] = useState<FormState>(DEFAULT);
  const [audio, setAudio] = useState<string | null>(null);
  const [response, setResponse] = useState<InterceptionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(k: keyof FormState) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm(prev => ({ ...prev, [k]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    setResponse(null);
    try {
      const res = await intercept({
        sender_account: form.sender_account,
        recipient_account: form.recipient_account,
        amount: parseFloat(form.amount),
        channel: form.channel,
        recipient_account_age_days: parseInt(form.recipient_account_age_days, 10),
        narrative_context: form.narrative_context,
        audio_base64: audio ?? undefined,
      });
      setResponse(res);
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'Interception request failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <VoiceAuthWidget onChange={setAudio} selected={audio} />

      <form
        onSubmit={handleSubmit}
        className="rounded-2xl p-5 space-y-3.5"
        style={{
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.07)',
        }}
      >
        <div
          className="flex items-center gap-2 pb-2.5"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}
        >
          <ArrowRightLeft size={14} className="text-indigo-400" />
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.6)' }}>
            Payment Parameters
          </h3>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Sender Account" value={form.sender_account} onChange={set('sender_account')} />
          <Field label="Recipient Account" value={form.recipient_account} onChange={set('recipient_account')} />
          <Field label="Amount (₹)" type="number" value={form.amount} onChange={set('amount')} />
          <div>
            <label className="mb-1 block text-xs font-medium" style={{ color: 'rgba(148,163,184,0.6)' }}>
              Payment Rail
            </label>
            <select
              value={form.channel}
              onChange={set('channel') as React.ChangeEventHandler<HTMLSelectElement>}
              className={INPUT_CLASS}
            >
              {CHANNELS.map(c => (
                <option key={c} value={c} style={{ background: '#18181f' }}>{c}</option>
              ))}
            </select>
          </div>
          <Field label="Recipient Account Age (days)" type="number" value={form.recipient_account_age_days} onChange={set('recipient_account_age_days')} />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium" style={{ color: 'rgba(148,163,184,0.6)' }}>
            Narrative Context / Voice Transcript
          </label>
          <textarea
            value={form.narrative_context}
            onChange={set('narrative_context')}
            rows={2}
            className={`${INPUT_CLASS} resize-none`}
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="primary w-full"
        >
          {loading ? <span className="animate-spin text-sm">↻</span> : <Send size={12} />}
          {loading ? 'Evaluating…' : 'Authorize Transaction'}
        </button>

        {err && (
          <p
            className="rounded-xl p-2.5 text-xs font-medium"
            style={{
              background: 'rgba(244,63,94,0.08)',
              border: '1px solid rgba(244,63,94,0.2)',
              color: '#fda4af',
            }}
          >
            {err}
          </p>
        )}
      </form>

      <OutcomeBanner response={response} />
    </div>
  );
}

function Field({
  label, value, onChange, type = 'text',
}: { label: string; value: string; onChange: React.ChangeEventHandler<HTMLInputElement>; type?: string }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium" style={{ color: 'rgba(148,163,184,0.6)' }}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={onChange}
        className={`w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-slate-200 placeholder:text-slate-700 focus:border-indigo-500/50 focus:outline-none transition-colors`}
      />
    </div>
  );
}
