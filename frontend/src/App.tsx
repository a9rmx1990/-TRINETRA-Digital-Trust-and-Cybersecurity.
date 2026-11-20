import { useEffect, useState } from 'react';
import { ShieldHalf } from 'lucide-react';
import { api } from './sandbox';
import type { SandboxConfig } from './sandbox';
import SandboxCaller from './components/SandboxCaller';
import SandboxSoc from './components/SandboxSoc';

export default function App() {
  const [tab, setTab] = useState<'caller' | 'soc'>('caller');
  const [config, setConfig] = useState<SandboxConfig>();
  const [error, setError] = useState('');
  const [analystKey, setAnalystKey] = useState('');
  const [preferredCaseId, setPreferredCaseId] = useState<string>();
  useEffect(() => { load(); }, []);

  function load() {
    setError('');
    void api<SandboxConfig>('/sandbox').then(setConfig).catch(() => setError('Could not connect to the sandbox API.'));
  }

  return (
    <div className="min-h-dvh" style={{ background: 'linear-gradient(180deg, #000000 0%, #0a0a0f 100%)' }}>

      {/* ── Header ───────────────────────────────────────────────────── */}
      <header
        className="sticky top-0 z-50 border-b"
        style={{
          background: 'rgba(0,0,0,0.75)',
          borderColor: 'rgba(255,255,255,0.06)',
          backdropFilter: 'blur(20px) saturate(1.4)',
          WebkitBackdropFilter: 'blur(20px) saturate(1.4)',
        }}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3.5">

          {/* Logo */}
          <div className="flex items-center gap-3 select-none">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-xl"
              style={{
                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                boxShadow: '0 0 16px rgba(99,102,241,0.4)',
              }}
            >
              <ShieldHalf size={16} className="text-white" aria-hidden="true" />
            </div>
            <div>
              <span
                className="text-sm font-bold tracking-[0.12em] text-white"
                style={{ letterSpacing: '0.12em' }}
              >
                TRINETRA
              </span>
              <span
                className="ml-2 hidden text-xs font-medium sm:inline"
                style={{ color: 'rgba(148,163,184,0.7)' }}
              >
                Banking Sandbox
              </span>
            </div>
          </div>

          {/* Tab switcher */}
          <nav
            aria-label="Portal views"
            className="flex overflow-hidden rounded-xl p-0.5 gap-0.5"
            style={{
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.07)',
            }}
          >
            {(['caller', 'soc'] as const).map(t => {
              const active = tab === t;
              const labels = { caller: 'Banking Portal', soc: 'Analyst Console' };
              return (
                <button
                  key={t}
                  aria-pressed={active}
                  onClick={() => setTab(t)}
                  className="cursor-pointer select-none rounded-lg px-4 py-1.5 text-xs font-medium transition-all duration-200"
                  style={active ? {
                    background: 'rgba(99,102,241,0.2)',
                    color: '#a5b4fc',
                    boxShadow: '0 0 0 1px rgba(99,102,241,0.3)',
                  } : {
                    color: 'rgba(148,163,184,0.6)',
                  }}
                >
                  {labels[t]}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* ── Main ─────────────────────────────────────────────────────── */}
      <main className="mx-auto max-w-7xl px-5 py-8">

        {error && (
          <div
            role="alert"
            className="mb-6 flex flex-wrap items-center gap-3 rounded-2xl border p-4 text-sm animate-entry"
            style={{
              background: 'rgba(244,63,94,0.08)',
              borderColor: 'rgba(244,63,94,0.2)',
              color: '#fda4af',
            }}
          >
            {error}
            <button className="secondary ml-auto text-xs" onClick={load}>Retry</button>
          </div>
        )}

        {!config && !error && (
          <div
            role="status"
            className="flex items-center gap-3 text-sm animate-entry"
            style={{ color: 'rgba(148,163,184,0.6)' }}
          >
            <span
              className="inline-block h-2 w-2 rounded-full blink"
              style={{ background: 'rgba(99,102,241,0.8)' }}
            />
            Connecting to sandbox…
          </div>
        )}

        {config && (
          <>
            <div hidden={tab !== 'caller'}>
              <SandboxCaller config={config} onSubmitPayment={setPreferredCaseId} />
            </div>
            {tab === 'soc' && (
              <SandboxSoc
                enabled={config.analyst_enabled}
                analystKey={analystKey}
                onKey={setAnalystKey}
                preferredCaseId={preferredCaseId}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
