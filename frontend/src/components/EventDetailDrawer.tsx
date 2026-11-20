/**
 * EventDetailDrawer — Slide-in drawer with full forensic inspection (OLED dark)
 */
import { useState } from 'react';
import { X, Lock, Unlock, CheckCircle2, AlertCircle } from 'lucide-react';
import { socOverride } from '../api';
import type { SOCEvent } from '../types';

interface Props {
  event: SOCEvent | null;
  onClose: () => void;
}

export default function EventDetailDrawer({ event, onClose }: Props) {
  const [actionMsg, setActionMsg] = useState<{ text: string; ok: boolean } | null>(null);

  if (!event) return null;

  const breakdown = event.breakdown ?? event.risk_breakdown;
  const acoustic_diagnostics = event.acoustic_diagnostics;
  const graph_diagnostics = event.graph_diagnostics;
  const decision = event.decision ?? 'HOLD';
  const txId = event.transaction?.transaction_id ?? event.transaction_id ?? event.account ?? 'TX-UNKNOWN';
  const targetAccount = event.account ?? event.transaction?.recipient_account ?? event.transaction?.sender_account ?? txId;

  async function doOverride(action: 'CONFIRM_FREEZE' | 'RELEASE_HOLD') {
    try {
      await socOverride(targetAccount, action);
      setActionMsg({
        text: action === 'CONFIRM_FREEZE' ? 'Account permanently quarantined' : 'Account released from quarantine',
        ok: true,
      });
    } catch {
      setActionMsg({ text: 'Analyst override action failed', ok: false });
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="flex-1 cursor-pointer"
        style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        className="flex w-full max-w-md flex-col overflow-y-auto"
        style={{
          background: '#0a0a0f',
          borderLeft: '1px solid rgba(255,255,255,0.08)',
          boxShadow: '-24px 0 60px rgba(0,0,0,0.6)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-4"
          style={{
            borderBottom: '1px solid rgba(255,255,255,0.07)',
            background: 'rgba(255,255,255,0.02)',
          }}
        >
          <div>
            <h2 className="text-sm font-bold text-slate-100">Forensic Incident Detail</h2>
            <p className="mt-0.5 font-mono text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{txId}</p>
          </div>
          <div className="flex items-center gap-2">
            <DecisionPill decision={decision} />
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 transition-colors cursor-pointer"
              style={{ color: 'rgba(148,163,184,0.5)' }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.08)'; (e.currentTarget as HTMLElement).style.color = '#e2e8f0'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = ''; (e.currentTarget as HTMLElement).style.color = 'rgba(148,163,184,0.5)'; }}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-5 p-4 text-xs">
          {/* Score breakdown */}
          {breakdown && (
            <Section title="Risk Model Breakdown">
              <div
                className="space-y-2.5 rounded-xl p-3"
                style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
              >
                <ScoreRow label="Acoustic Forensic (w=0.45)" value={breakdown.acoustic_score} />
                <ScoreRow label="Graph Network (w=0.40)" value={breakdown.graph_score} />
                <ScoreRow label="NLP Threat (w=0.15)" value={breakdown.nlp_score} />
                <div className="border-t pt-2.5" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
                  <ScoreRow label="Composite Risk Score" value={breakdown.composite_risk} bold />
                </div>
              </div>
            </Section>
          )}

          {/* Threat signals */}
          {event.reasons && event.reasons.length > 0 && (
            <Section title="Threat Signals Detected">
              <ul
                className="space-y-1.5 rounded-xl p-3"
                style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
              >
                {event.reasons.map((r, i) => (
                  <li key={i} className="flex items-start gap-1.5" style={{ color: 'rgba(148,163,184,0.75)' }}>
                    <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-indigo-500" />
                    {r}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* Acoustic diagnostics */}
          {acoustic_diagnostics && (
            <Section title="Acoustic DSP Analysis">
              <div
                className="grid grid-cols-2 gap-2 rounded-xl p-3"
                style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
              >
                <Kv k="Synthetic Audio" v={acoustic_diagnostics.is_synthetic ? 'DETECTED' : 'CLEAN'} highlight={acoustic_diagnostics.is_synthetic} />
                <Kv k="Confidence" v={`${(acoustic_diagnostics.confidence * 100).toFixed(0)}%`} />
                <Kv k="Wiener Flatness" v={acoustic_diagnostics.spectral_flatness.toFixed(4)} />
                <Kv k="HF Power (>4kHz)" v={`${(acoustic_diagnostics.high_freq_ratio * 100).toFixed(1)}%`} />
                <Kv k="Spectral Rolloff" v={`${acoustic_diagnostics.spectral_rolloff.toFixed(0)} Hz`} />
              </div>
            </Section>
          )}

          {/* Graph diagnostics */}
          {graph_diagnostics && (
            <Section title="Network Graph Diagnostics">
              <div
                className="grid grid-cols-2 gap-2 rounded-xl p-3"
                style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
              >
                <Kv k="Hop Depth" v={graph_diagnostics.hop_count} />
                <Kv k="Dispersion Velocity" v={(graph_diagnostics.dispersion_velocity ?? graph_diagnostics.velocity ?? 0).toFixed(2)} />
                <Kv k="Cycle Detected" v={graph_diagnostics.cycle_detected ? 'CONFIRMED' : 'NONE'} highlight={graph_diagnostics.cycle_detected} />
                <Kv k="Quarantined Nodes" v={graph_diagnostics.quarantined_nodes.length} />
              </div>
              {graph_diagnostics.quarantined_nodes.length > 0 && (
                <div
                  className="mt-2 rounded-xl p-2.5"
                  style={{ background: 'rgba(244,63,94,0.08)', border: '1px solid rgba(244,63,94,0.2)' }}
                >
                  <p className="text-xs font-semibold" style={{ color: '#fb7185' }}>Quarantined Accounts:</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {graph_diagnostics.quarantined_nodes.map(n => (
                      <span
                        key={n}
                        className="rounded-lg px-1.5 py-0.5 font-mono text-xs font-semibold"
                        style={{
                          background: 'rgba(244,63,94,0.12)',
                          color: '#fb7185',
                          border: '1px solid rgba(244,63,94,0.2)',
                        }}
                      >
                        {n}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          )}

          {/* Analyst actions */}
          {decision === 'HOLD' && (
            <Section title="Analyst Controls">
              {actionMsg ? (
                <div
                  className="flex items-center gap-2 rounded-xl p-3 text-xs font-medium"
                  style={actionMsg.ok ? {
                    background: 'rgba(16,185,129,0.08)',
                    border: '1px solid rgba(16,185,129,0.2)',
                    color: '#34d399',
                  } : {
                    background: 'rgba(244,63,94,0.08)',
                    border: '1px solid rgba(244,63,94,0.2)',
                    color: '#fb7185',
                  }}
                >
                  {actionMsg.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                  {actionMsg.text}
                </div>
              ) : (
                <div className="flex gap-2">
                  <button
                    onClick={() => doOverride('CONFIRM_FREEZE')}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all cursor-pointer"
                    style={{
                      background: 'rgba(244,63,94,0.15)',
                      border: '1px solid rgba(244,63,94,0.3)',
                      color: '#fb7185',
                    }}
                  >
                    <Lock size={11} />
                    Confirm Freeze
                  </button>
                  <button
                    onClick={() => doOverride('RELEASE_HOLD')}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all cursor-pointer"
                    style={{
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      color: 'rgba(148,163,184,0.8)',
                    }}
                  >
                    <Unlock size={11} />
                    Release Hold
                  </button>
                </div>
              )}
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.45)' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function ScoreRow({ label, value, bold }: { label: string; value: number; bold?: boolean }) {
  const pct = Math.min(100, value);
  const barColor = value >= 70 ? '#f43f5e' : value >= 35 ? '#f59e0b' : '#10b981';
  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className={`w-40 ${bold ? 'font-bold text-slate-200' : ''}`}
        style={{ color: bold ? '#e2e8f0' : 'rgba(148,163,184,0.7)' }}
      >
        {label}
      </span>
      <div className="flex-1 overflow-hidden rounded-full h-1.5" style={{ background: 'rgba(255,255,255,0.08)' }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: barColor }} />
      </div>
      <span
        className={`w-10 text-right font-mono ${bold ? 'font-bold' : ''}`}
        style={{ color: bold ? '#e2e8f0' : 'rgba(148,163,184,0.7)' }}
      >
        {value.toFixed(1)}
      </span>
    </div>
  );
}

function Kv({ k, v, highlight }: { k: string; v: string | number; highlight?: boolean }) {
  return (
    <div>
      <span style={{ color: 'rgba(148,163,184,0.5)' }}>{k}: </span>
      <span
        className="font-medium"
        style={{ color: highlight ? '#fb7185' : 'rgba(226,232,240,0.9)' }}
      >
        {v}
      </span>
    </div>
  );
}

function DecisionPill({ decision }: { decision: string }) {
  const styles: Record<string, React.CSSProperties> = {
    ALLOW: { background: 'rgba(16,185,129,0.1)', color: '#34d399', border: '1px solid rgba(16,185,129,0.2)' },
    STEP_UP: { background: 'rgba(245,158,11,0.1)', color: '#fbbf24', border: '1px solid rgba(245,158,11,0.2)' },
    HOLD: { background: 'rgba(244,63,94,0.1)', color: '#fb7185', border: '1px solid rgba(244,63,94,0.2)' },
  };
  return (
    <span
      className="rounded-lg px-2 py-0.5 text-xs font-bold uppercase tracking-wider"
      style={styles[decision] ?? { background: 'rgba(255,255,255,0.08)', color: '#94a3b8', border: '1px solid rgba(255,255,255,0.1)' }}
    >
      {decision}
    </span>
  );
}
