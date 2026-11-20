/**
 * ScenarioBar — Preset attack scenario simulation triggers (OLED dark)
 */
import { useEffect, useState } from 'react';
import { CheckCircle2, MicOff, Network, AlertOctagon, Zap } from 'lucide-react';
import { getScenarios, triggerScenario } from '../api';
import type { ScenarioMeta } from '../types';

interface Props {
  onTriggered: () => void;
}

export default function ScenarioBar({ onTriggered }: Props) {
  const [scenarios, setScenarios] = useState<ScenarioMeta[]>([]);
  const [loading, setLoading] = useState<string | null>(null);

  useEffect(() => {
    getScenarios().then(setScenarios).catch(() => {});
  }, []);

  async function trigger(id: string) {
    setLoading(id);
    try {
      await triggerScenario(id);
      onTriggered();
    } finally {
      setLoading(null);
    }
  }

  function getScenarioIcon(id: string) {
    switch (id) {
      case 'SCENARIO_1_BASELINE':
        return <CheckCircle2 size={12} className="text-emerald-400" />;
      case 'SCENARIO_2_VOICE_CLONE':
        return <MicOff size={12} className="text-red-400" />;
      case 'SCENARIO_3_MULE_RING':
        return <Network size={12} className="text-amber-400" />;
      case 'SCENARIO_4_DIGITAL_ARREST':
        return <AlertOctagon size={12} className="text-purple-400" />;
      default:
        return <Zap size={12} className="text-indigo-400" />;
    }
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-xl p-3"
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.07)',
      }}
    >
      <div
        className="flex items-center gap-1.5 px-1 text-xs font-semibold uppercase tracking-wider"
        style={{ color: 'rgba(148,163,184,0.5)' }}
      >
        <Zap size={11} className="text-indigo-400" />
        <span>Scenarios</span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {scenarios.map(s => (
          <button
            key={s.id}
            onClick={() => trigger(s.id)}
            disabled={loading === s.id}
            title={s.description}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all duration-150 cursor-pointer disabled:opacity-50"
            style={{
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: 'rgba(148,163,184,0.8)',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLElement).style.background = 'rgba(99,102,241,0.08)';
              (e.currentTarget as HTMLElement).style.borderColor = 'rgba(99,102,241,0.25)';
              (e.currentTarget as HTMLElement).style.color = '#a5b4fc';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)';
              (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.08)';
              (e.currentTarget as HTMLElement).style.color = 'rgba(148,163,184,0.8)';
            }}
          >
            {loading === s.id ? (
              <span className="animate-spin text-indigo-400 text-xs">↻</span>
            ) : (
              getScenarioIcon(s.id)
            )}
            <span>{s.title ?? s.name ?? s.id}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
