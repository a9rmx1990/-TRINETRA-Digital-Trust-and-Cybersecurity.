/**
 * SOCConsole — Security analyst command console (OLED dark)
 */
import { useState } from 'react';
import { Radio } from 'lucide-react';
import type { SOCEvent, CytoscapeGraph, AcousticDiagnostics } from '../types';
import ScenarioBar from './ScenarioBar';
import LiveFeed from './LiveFeed';
import GraphPanel from './GraphPanel';
import SpectrogramPanel from './SpectrogramPanel';

interface Props {
  events: SOCEvent[];
  latestGraph: CytoscapeGraph | null;
}

export default function SOCConsole({ events, latestGraph }: Props) {
  const [lastAcoustic, setLastAcoustic] = useState<AcousticDiagnostics | null>(null);

  function handleScenarioTriggered() {
    const holdEvent = events.find(e => e.decision === 'HOLD' && e.acoustic_diagnostics);
    if (holdEvent?.acoustic_diagnostics) setLastAcoustic(holdEvent.acoustic_diagnostics);
  }

  const feedAcoustic = events.find(e => e.acoustic_diagnostics)?.acoustic_diagnostics ?? null;
  const displayAcoustic = lastAcoustic ?? feedAcoustic;

  return (
    <div className="p-4 space-y-4">
      {/* Scenario control bar */}
      <ScenarioBar onTriggered={handleScenarioTriggered} />

      {/* Main console grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Live feed — 3 cols */}
        <div className="lg:col-span-3 space-y-2">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <Radio size={13} className="text-indigo-400 animate-pulse" />
              <h2 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.6)' }}>
                Live Interception Stream
              </h2>
            </div>
            <span
              className="rounded-full px-2.5 py-0.5 text-xs font-mono font-medium"
              style={{
                background: 'rgba(99,102,241,0.1)',
                border: '1px solid rgba(99,102,241,0.15)',
                color: '#a5b4fc',
              }}
            >
              {events.length} events
            </span>
          </div>
          <LiveFeed events={events} />
        </div>

        {/* Right column — 2 cols */}
        <div className="space-y-4 lg:col-span-2">
          <GraphPanel latestGraph={latestGraph} />
          <SpectrogramPanel diagnostics={displayAcoustic} />
        </div>
      </div>
    </div>
  );
}
