/**
 * LiveFeed — Real-time SOC transaction telemetry feed (OLED dark)
 */
import { useState } from 'react';
import type { SOCEvent } from '../types';
import EventDetailDrawer from './EventDetailDrawer';
import { Radio } from 'lucide-react';

interface Props {
  events: SOCEvent[];
}

const DECISION_STYLE: Record<string, { bg: string; color: string; border: string; label: string }> = {
  ALLOW: {
    bg: 'rgba(16,185,129,0.1)',
    color: '#34d399',
    border: 'rgba(16,185,129,0.2)',
    label: 'ALLOW',
  },
  STEP_UP: {
    bg: 'rgba(245,158,11,0.1)',
    color: '#fbbf24',
    border: 'rgba(245,158,11,0.2)',
    label: 'STEP-UP',
  },
  HOLD: {
    bg: 'rgba(244,63,94,0.1)',
    color: '#fb7185',
    border: 'rgba(244,63,94,0.2)',
    label: 'HOLD',
  },
};

export default function LiveFeed({ events }: Props) {
  const [selected, setSelected] = useState<SOCEvent | null>(null);

  if (events.length === 0) {
    return (
      <div
        className="flex h-48 flex-col items-center justify-center rounded-xl p-6 text-center text-xs"
        style={{
          border: '1px dashed rgba(99,102,241,0.2)',
          background: 'rgba(99,102,241,0.03)',
          color: 'rgba(148,163,184,0.5)',
        }}
      >
        <Radio size={16} className="mb-2 text-indigo-500 opacity-50" />
        <p className="font-medium text-slate-400">No transactions intercepted yet</p>
        <p className="mt-1" style={{ color: 'rgba(148,163,184,0.4)' }}>
          Trigger a demo attack scenario above or send a transfer from the Banking Portal.
        </p>
      </div>
    );
  }

  return (
    <>
      <div
        className="live-feed-scroll max-h-[580px] overflow-auto rounded-xl"
        style={{ border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <table className="w-full text-xs">
          <thead
            className="sticky top-0 z-10"
            style={{
              background: 'rgba(10,10,15,0.9)',
              backdropFilter: 'blur(12px)',
              borderBottom: '1px solid rgba(255,255,255,0.07)',
            }}
          >
            <tr>
              {['Time', 'Transaction ID', 'Channel', 'Amount', 'Decision', 'Latency'].map((h, i) => (
                <th
                  key={h}
                  className={`px-3.5 py-2.5 font-semibold ${i === 3 ? 'text-right' : i === 4 ? 'text-center' : i === 5 ? 'text-right' : 'text-left'}`}
                  style={{ color: 'rgba(148,163,184,0.5)' }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map((ev, idx) => {
              const txId = ev.transaction?.transaction_id ?? ev.transaction_id ?? `TX-EVT-${idx}`;
              const channel = ev.transaction?.channel ?? ev.channel ?? 'UPI';
              const amount = ev.transaction?.amount ?? ev.amount ?? 0;
              const decision = ev.decision ?? 'ALLOW';
              const latency = ev.latency_ms ?? 0;
              const style = DECISION_STYLE[decision] ?? DECISION_STYLE.ALLOW;
              const isHold = decision === 'HOLD';

              return (
                <tr
                  key={`${txId}-${idx}`}
                  onClick={() => setSelected(ev)}
                  className="cursor-pointer transition-colors"
                  style={{
                    borderTop: '1px solid rgba(255,255,255,0.04)',
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)';
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.background = '';
                  }}
                >
                  <td className="px-3.5 py-2.5 font-mono" style={{ color: 'rgba(148,163,184,0.5)' }}>
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </td>
                  <td className="px-3.5 py-2.5 font-mono font-medium text-slate-300">
                    {txId.slice(0, 16)}…
                  </td>
                  <td className="px-3.5 py-2.5 font-medium" style={{ color: 'rgba(148,163,184,0.7)' }}>
                    {channel}
                  </td>
                  <td className="px-3.5 py-2.5 text-right font-mono font-semibold text-slate-200">
                    ₹{amount.toLocaleString()}
                  </td>
                  <td className="px-3.5 py-2.5 text-center">
                    <span
                      className={`inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-semibold${isHold ? ' hold-pulse' : ''}`}
                      style={{
                        background: style.bg,
                        color: style.color,
                        border: `1px solid ${style.border}`,
                      }}
                    >
                      {style.label}
                    </span>
                  </td>
                  <td className="px-3.5 py-2.5 text-right font-mono" style={{ color: 'rgba(148,163,184,0.5)' }}>
                    {latency.toFixed(1)}ms
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <EventDetailDrawer event={selected} onClose={() => setSelected(null)} />
    </>
  );
}
