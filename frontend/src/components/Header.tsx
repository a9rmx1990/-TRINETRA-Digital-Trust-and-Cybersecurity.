import { useEffect, useState } from 'react';
import { ShieldHalf, Landmark, ShieldCheck } from 'lucide-react';
import { getHealth, getMetrics } from '../api';
import type { Metrics } from '../types';

type Tab = 'PORTAL' | 'SOC';

interface Props {
  activeTab: Tab;
  onTabChange: (t: Tab) => void;
  wsConnected: boolean;
}

export default function Header({ activeTab, onTabChange, wsConnected }: Props) {
  const [live, setLive] = useState(false);
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  useEffect(() => {
    const poll = async () => {
      try { await getHealth(); setLive(true); } catch { setLive(false); }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const poll = async () => {
      try { setMetrics(await getMetrics()); } catch { /* backend offline */ }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  return (
    <header
      className="sticky top-0 z-50 border-b"
      style={{
        background: 'rgba(0,0,0,0.75)',
        borderColor: 'rgba(255,255,255,0.06)',
        backdropFilter: 'blur(20px) saturate(1.4)',
        WebkitBackdropFilter: 'blur(20px) saturate(1.4)',
      }}
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-5 py-3.5">

        {/* Logo */}
        <div className="flex items-center gap-2.5 select-none">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-xl"
            style={{
              background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
              boxShadow: '0 0 14px rgba(99,102,241,0.4)',
            }}
          >
            <ShieldHalf size={14} className="text-white" aria-hidden="true" />
          </div>
          <div className="flex flex-col sm:flex-row sm:items-baseline sm:gap-2">
            <span className="text-xs font-bold tracking-[0.12em] text-white uppercase">TRINETRA</span>
            <span className="hidden text-xs sm:inline" style={{ color: 'rgba(148,163,184,0.5)' }}>
              Real-Time AI Fraud Interceptor
            </span>
          </div>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Metric chips */}
        {metrics && (
          <div className="hidden gap-2 md:flex">
            <Chip label="Evaluated" value={metrics.total_evaluated} />
            <Chip label="HOLD" value={metrics.held} color="#fb7185" />
            <Chip label="STEP-UP" value={metrics.stepped_up} color="#fbbf24" />
            <Chip label="p50 Latency" value={`${metrics.average_latency_ms.toFixed(1)}ms`} color="#a5b4fc" />
          </div>
        )}

        {/* Backend status */}
        <span
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-mono font-medium"
          style={live ? {
            background: 'rgba(16,185,129,0.1)',
            border: '1px solid rgba(16,185,129,0.2)',
            color: '#34d399',
          } : {
            background: 'rgba(244,63,94,0.1)',
            border: '1px solid rgba(244,63,94,0.2)',
            color: '#fb7185',
          }}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full${live ? ' blink' : ''}`}
            style={{ background: live ? '#34d399' : '#f43f5e' }}
          />
          {live ? 'API LIVE' : 'OFFLINE'}
        </span>

        {/* WS status */}
        <span
          className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-mono font-medium"
          style={wsConnected ? {
            background: 'rgba(99,102,241,0.1)',
            border: '1px solid rgba(99,102,241,0.2)',
            color: '#a5b4fc',
          } : {
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.07)',
            color: 'rgba(148,163,184,0.5)',
          }}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full${wsConnected ? ' blink' : ''}`}
            style={{ background: wsConnected ? '#6366f1' : 'rgba(148,163,184,0.3)' }}
          />
          {wsConnected ? 'LIVE' : 'WS IDLE'}
        </span>

        {/* Tab switcher */}
        <div
          className="flex overflow-hidden rounded-xl p-0.5 gap-0.5"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.07)',
          }}
        >
          <TabBtn icon={<Landmark size={12} />} label="Banking Portal" value="PORTAL" active={activeTab} onClick={onTabChange} />
          <TabBtn icon={<ShieldCheck size={12} />} label="SOC Console" value="SOC" active={activeTab} onClick={onTabChange} />
        </div>
      </div>
    </header>
  );
}

function Chip({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div
      className="rounded-lg px-2.5 py-1 text-xs"
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.07)',
      }}
    >
      <span style={{ color: 'rgba(148,163,184,0.5)' }}>{label}: </span>
      <span className="font-mono font-semibold" style={{ color: color ?? '#e2e8f0' }}>{value}</span>
    </div>
  );
}

function TabBtn({
  icon, label, value, active, onClick,
}: { icon: React.ReactNode; label: string; value: Tab; active: Tab; onClick: (v: Tab) => void }) {
  const isActive = active === value;
  return (
    <button
      onClick={() => onClick(value)}
      className="cursor-pointer flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-200"
      style={isActive ? {
        background: 'rgba(99,102,241,0.2)',
        color: '#a5b4fc',
        boxShadow: '0 0 0 1px rgba(99,102,241,0.3)',
      } : {
        background: 'transparent',
        color: 'rgba(148,163,184,0.6)',
      }}
    >
      {icon}
      {label}
    </button>
  );
}
