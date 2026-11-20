/**
 * SpectrogramPanel — Visual acoustic forensics display (OLED dark)
 */
import { useRef, useEffect } from 'react';
import { Activity, AlertTriangle } from 'lucide-react';
import type { AcousticDiagnostics } from '../types';

interface Props {
  diagnostics: AcousticDiagnostics | null;
}

export default function SpectrogramPanel({ diagnostics }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !diagnostics) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    drawSpectrogram(ctx, canvas.width, canvas.height, diagnostics);
  }, [diagnostics]);

  if (!diagnostics) {
    return (
      <div
        className="flex h-44 flex-col items-center justify-center rounded-xl p-4 text-center text-xs"
        style={{
          border: '1px dashed rgba(99,102,241,0.15)',
          background: 'rgba(99,102,241,0.03)',
          color: 'rgba(148,163,184,0.4)',
        }}
      >
        <Activity size={16} className="mb-1 text-indigo-500 opacity-40" />
        <span className="font-medium text-slate-500">Acoustic Telemetry Inactive</span>
        <span className="mt-1" style={{ color: 'rgba(148,163,184,0.35)' }}>
          Trigger an authorization call or scenario to render FFT spectrogram.
        </span>
      </div>
    );
  }

  const { is_synthetic, confidence, spectral_flatness, high_freq_ratio, spectral_rolloff } = diagnostics;

  return (
    <div
      className="rounded-xl p-3.5 space-y-3"
      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={13} className="text-indigo-400" />
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.6)' }}>
            Acoustic Forensics
          </h3>
        </div>
        {is_synthetic && (
          <span
            className="hold-pulse flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-bold"
            style={{
              background: 'rgba(244,63,94,0.12)',
              border: '1px solid rgba(244,63,94,0.3)',
              color: '#fb7185',
            }}
          >
            <AlertTriangle size={10} />
            SYNTHETIC
          </span>
        )}
      </div>

      {/* Spectrogram canvas */}
      <canvas
        ref={canvasRef}
        width={320}
        height={80}
        className="w-full rounded-lg"
        style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.06)' }}
      />

      {/* Gauges */}
      <div className="grid grid-cols-3 gap-2">
        <Gauge label="Flatness" value={spectral_flatness} max={1} danger={spectral_flatness > 0.03} />
        <Gauge label="Synthetic" value={confidence} max={1} danger={confidence > 0.7} pct />
        <Gauge label="HF Power" value={high_freq_ratio} max={1} danger={high_freq_ratio > 0.18} pct />
      </div>

      <div
        className="flex items-center justify-between text-xs border-t pt-2"
        style={{ borderColor: 'rgba(255,255,255,0.06)', color: 'rgba(148,163,184,0.5)' }}
      >
        <span>
          Rolloff: <span className="font-mono" style={{ color: 'rgba(148,163,184,0.8)' }}>{spectral_rolloff.toFixed(0)} Hz</span>
        </span>
        {high_freq_ratio > 0.18 && (
          <span style={{ color: '#fb7185' }} className="font-medium text-xs">Phase vocoder artifact</span>
        )}
      </div>
    </div>
  );
}

function Gauge({
  label, value, max, danger, pct = false,
}: { label: string; value: number; max: number; danger: boolean; pct?: boolean }) {
  const pctVal = Math.min(100, (value / max) * 100);
  return (
    <div
      className="rounded-lg p-2 text-center"
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: `1px solid ${danger ? 'rgba(244,63,94,0.2)' : 'rgba(255,255,255,0.06)'}`,
      }}
    >
      <div className="truncate text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{label}</div>
      <div
        className="mt-0.5 text-xs font-bold font-mono"
        style={{ color: danger ? '#fb7185' : '#34d399' }}
      >
        {pct ? `${(value * 100).toFixed(0)}%` : value.toFixed(4)}
      </div>
      <div
        className="mt-1.5 h-1 overflow-hidden rounded-full"
        style={{ background: 'rgba(255,255,255,0.08)' }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pctVal}%`,
            background: danger ? '#f43f5e' : '#10b981',
          }}
        />
      </div>
    </div>
  );
}

function drawSpectrogram(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  d: AcousticDiagnostics,
) {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(0,0,0,0)';
  ctx.fillRect(0, 0, W, H);

  const BARS = 32;
  const barW = (W - BARS) / BARS;
  const rolloffBin = Math.round((d.spectral_rolloff / 8000) * BARS);
  const hfThresh = Math.round(0.5 * BARS);

  for (let i = 0; i < BARS; i++) {
    const roll = i < rolloffBin ? 1 : Math.exp(-(i - rolloffBin) * 0.3);
    const hfBump = i > hfThresh && d.is_synthetic ? d.high_freq_ratio * 1.5 : 0;
    const mag = Math.min(1, roll * (0.4 + Math.random() * 0.25) + hfBump);
    const barH = Math.max(3, mag * (H - 10));
    const x = i * (barW + 1);
    const isHFAnomaly = i >= hfThresh && d.high_freq_ratio > 0.18;

    if (isHFAnomaly) {
      ctx.fillStyle = '#f43f5e';
    } else if (i < rolloffBin) {
      // Gradient: indigo to purple
      const alpha = 0.5 + mag * 0.4;
      ctx.fillStyle = `rgba(99,102,241,${alpha})`;
    } else {
      ctx.fillStyle = `rgba(99,102,241,0.25)`;
    }
    ctx.fillRect(x, H - barH, barW, barH);
  }

  // 4kHz demarcation
  const markerX = hfThresh * (barW + 1);
  ctx.strokeStyle = 'rgba(245,158,11,0.6)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(markerX, 0);
  ctx.lineTo(markerX, H);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = 'rgba(245,158,11,0.7)';
  ctx.font = '8px system-ui, sans-serif';
  ctx.fillText('4 kHz', markerX + 3, 10);
}
