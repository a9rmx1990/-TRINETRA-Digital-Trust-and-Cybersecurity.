/**
 * OutcomeBanner — Displays real-time fraud policy outcome (OLED dark)
 */
import { CheckCircle2, AlertTriangle, ShieldAlert } from 'lucide-react';
import type { InterceptionResponse } from '../types';

interface Props {
  response: InterceptionResponse | null;
}

export default function OutcomeBanner({ response }: Props) {
  if (!response) return null;

  const { decision, composite_risk, latency_ms, reasons } = response;

  const cfg = {
    ALLOW: {
      style: { background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' },
      badgeStyle: { background: 'rgba(16,185,129,0.15)', color: '#34d399', border: '1px solid rgba(16,185,129,0.25)' },
      textColor: '#34d399',
      icon: <CheckCircle2 size={18} style={{ color: '#34d399' }} className="shrink-0" />,
      title: 'Payment Cleared & Dispatched',
    },
    STEP_UP: {
      style: { background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)' },
      badgeStyle: { background: 'rgba(245,158,11,0.15)', color: '#fbbf24', border: '1px solid rgba(245,158,11,0.25)' },
      textColor: '#fbbf24',
      icon: <AlertTriangle size={18} style={{ color: '#fbbf24' }} className="shrink-0" />,
      title: 'Additional Verification Required',
    },
    HOLD: {
      style: { background: 'rgba(244,63,94,0.08)', border: '1px solid rgba(244,63,94,0.2)' },
      badgeStyle: { background: 'rgba(244,63,94,0.15)', color: '#fb7185', border: '1px solid rgba(244,63,94,0.25)' },
      textColor: '#fb7185',
      icon: <ShieldAlert size={18} style={{ color: '#fb7185' }} className="shrink-0" />,
      title: 'Transaction Intercepted & Quarantined',
    },
  }[decision] ?? {
    style: { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' },
    badgeStyle: { background: 'rgba(255,255,255,0.08)', color: '#94a3b8', border: '1px solid rgba(255,255,255,0.1)' },
    textColor: '#94a3b8',
    icon: null,
    title: decision,
  };

  return (
    <div
      className="mt-4 rounded-xl p-4 animate-entry"
      style={cfg.style}
    >
      <div className="flex items-start gap-3">
        {cfg.icon}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="rounded-lg px-2 py-0.5 text-xs font-bold uppercase tracking-wider"
              style={cfg.badgeStyle}
            >
              {decision}
            </span>
            <span className="text-sm font-semibold" style={{ color: cfg.textColor }}>
              {cfg.title}
            </span>
            {decision === 'HOLD' && (
              <span
                className="hold-pulse rounded-lg px-2 py-0.5 text-xs font-bold"
                style={{
                  background: 'rgba(244,63,94,0.12)',
                  color: '#fb7185',
                  border: '1px solid rgba(244,63,94,0.25)',
                }}
              >
                FROZEN
              </span>
            )}
          </div>

          <div className="mt-2 flex gap-5 text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
            <span>
              Risk: <span className="font-mono font-semibold text-slate-300">{composite_risk.toFixed(1)}/100</span>
            </span>
            <span>
              Latency: <span className="font-mono font-semibold text-slate-300">{latency_ms.toFixed(2)}ms</span>
            </span>
          </div>

          {reasons.length > 0 && (
            <ul
              className="mt-2.5 space-y-1 rounded-xl p-2.5"
              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
            >
              {reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-1.5 text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-indigo-500" />
                  {r}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
