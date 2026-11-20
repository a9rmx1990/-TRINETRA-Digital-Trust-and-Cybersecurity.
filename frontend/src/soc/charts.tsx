import { useMemo, useState } from "react";
import { formatDateTime, formatDay, formatDuration } from "../lib/format";
import type { Analytics, Evidence } from "./api";
import { ChartFrame, DECISION_LABEL, Th } from "./ui";

export const DECISION_COLOR: Record<string, string> = { ALLOW: "rgb(var(--ui-blue))", STEP_UP: "rgb(var(--ui-amber))", HOLD: "rgb(var(--ui-red))", BLOCK: "rgb(var(--ui-red))" };
const DECISIONS = ["ALLOW", "STEP_UP", "HOLD", "BLOCK"] as const;

function Patterns() {
  return (
    <defs>
      <pattern id="hatch-block" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="5" height="5" fill="rgb(var(--ui-red))" />
        <line x1="0" y1="0" x2="0" y2="5" stroke="#FFFFFF" strokeWidth="2" />
      </pattern>
    </defs>
  );
}
const fillFor = (d: string) => (d === "BLOCK" ? "url(#hatch-block)" : DECISION_COLOR[d]);

export function Legend() {
  return (
    <ul className="flex flex-wrap gap-3 text-xs text-soc-muted">
      {DECISIONS.map((d) => (
        <li key={d} className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden><Patterns /><rect width="10" height="10" rx="2" fill={fillFor(d)} /></svg>
          {DECISION_LABEL[d]}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- volume
export function VolumeChart({ a, tz, onSelect, selected }: {
  a: Analytics; tz: string; onSelect: (b: { start_ms: number; end_ms: number; decision?: string }) => void;
  selected: { start_ms: number; decision?: string } | null;
}) {
  const bs = a.volume.buckets;
  const max = Math.max(1, ...bs.map((b) => b.total));
  const W = 640, H = 170, padL = 28, padB = 22;
  const bw = (W - padL) / Math.max(1, bs.length);
  const hourly = a.interval_ms <= 3_600_000;
  const label = (ms: number) => hourly ? new Intl.DateTimeFormat("en-IN", { hour: "2-digit", hour12: false, timeZone: tz }).format(ms) : formatDay(ms, tz);
  const every = Math.ceil(bs.length / 8);
  const ticks = [...new Set([0, Math.ceil(max / 2), max])];

  const table = (
    <div className="max-h-64 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-soc-panel"><tr><Th>Interval start</Th>{DECISIONS.map((d) => <Th key={d} right>{DECISION_LABEL[d]}</Th>)}<Th right>Total</Th></tr></thead>
        <tbody className="num">
          {bs.map((b) => (
            <tr key={b.start_ms} className="border-t border-soc-line/60">
              <td className="px-2 py-1"><button className="underline-offset-2 hover:underline" onClick={() => onSelect(b)}>{formatDateTime(b.start_ms, tz)}</button></td>
              {DECISIONS.map((d) => <td key={d} className="px-2 py-1 text-right">{b[d]}</td>)}
              <td className="px-2 py-1 text-right font-semibold">{b.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <ChartFrame title="Payment volume and outcomes"
      description="Distinct payments by initial gateway decision, grouped by creation time. Select a bar segment to list its payments."
      aside={<Legend />} table={table}
      chart={
        <svg viewBox={`0 0 ${W} ${H + padB}`} className="w-full" role="img"
             aria-label={`${a.volume.totals.total} payments across ${bs.length} intervals. Use Show table for values.`}>
          <Patterns />
          {ticks.map((t) => {
            const y = H - (t / max) * (H - 8);
            return <g key={t}><line x1={padL} x2={W} y1={y} y2={y} stroke="rgb(var(--ui-control))" strokeWidth="1" />
              <text x={padL - 6} y={y + 3} textAnchor="end" className="fill-soc-faint text-[10px] num">{t}</text></g>;
          })}
          {bs.map((b, i) => {
            let y = H;
            const x = padL + i * bw + bw * 0.15;
            const w = Math.max(1, bw * 0.7);
            return (
              <g key={b.start_ms}>
                {b.total === 0 && <rect x={x} y={H - 1} width={w} height={1} fill="rgb(var(--ui-control))" />}
                {DECISIONS.map((d) => {
                  if (!b[d]) return null;
                  const h = (b[d] / max) * (H - 8);
                  y -= h;
                  const sel = selected?.start_ms === b.start_ms && (!selected.decision || selected.decision === d);
                  return (
                    <rect key={d} x={x} y={y} width={w} height={h} fill={fillFor(d)} rx="1"
                          className="cursor-pointer outline-none" tabIndex={0} role="button"
                          stroke={sel ? "rgb(var(--ui-ink))" : "none"} strokeWidth={sel ? 1.5 : 0}
                          aria-label={`${b[d]} ${DECISION_LABEL[d]} from ${formatDateTime(b.start_ms, tz)}`}
                          onClick={() => onSelect({ start_ms: b.start_ms, end_ms: b.end_ms, decision: d })}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect({ start_ms: b.start_ms, end_ms: b.end_ms, decision: d }); } }}>
                      <title>{`${DECISION_LABEL[d]}: ${b[d]}`}</title>
                    </rect>
                  );
                })}
                {i % every === 0 && <text x={x + w / 2} y={H + 15} textAnchor="middle" className="fill-soc-faint text-[10px] num">{label(b.start_ms)}</text>}
              </g>
            );
          })}
        </svg>
      } />
  );
}

// ---------------------------------------------------------------- queue age
const AGE = [["lt_1h", "< 1 h"], ["1h_4h", "1–4 h"], ["4h_24h", "4–24 h"], ["gt_24h", "> 24 h"]] as const;
const PRIO = [["1", "High"], ["2", "Medium"], ["3", "Low"]] as const;

export function QueueAgeChart({ a, onSelect }: { a: Analytics; onSelect: (priority: string, age: string) => void }) {
  const m = a.queue.open_by_priority_age;
  const max = Math.max(1, ...Object.values(m).flatMap((r) => Object.values(r)));
  const grid = (asTable: boolean) => (
    <table className={`w-full text-sm ${asTable ? "" : "border-separate border-spacing-1"}`}>
      <thead><tr><Th>Priority</Th>{AGE.map(([k, l]) => <Th key={k} right={asTable}>{l}</Th>)}</tr></thead>
      <tbody>
        {PRIO.map(([p, pl]) => (
          <tr key={p}>
            <th scope="row" className="px-2 py-1 text-left text-xs font-medium text-soc-muted">{pl}</th>
            {AGE.map(([k, l]) => {
              const n = m[p]?.[k] ?? 0;
              return asTable ? <td key={k} className="num px-2 py-1 text-right">{n}</td> : (
                <td key={k} className="p-0">
                  <button onClick={() => onSelect(p, k)} disabled={!n}
                          aria-label={`${n} open ${pl.toLowerCase()} priority cases aged ${l}`}
                          className="num h-10 w-full rounded text-sm font-semibold transition-colors disabled:cursor-default"
                          style={{ background: n ? `rgb(var(--ui-blue) / ${0.12 + 0.24 * (n / max)})` : "rgb(var(--ui-canvas))",
                                   color: n ? "rgb(var(--ui-ink))" : "rgb(var(--ui-muted))" }}>
                    {n}
                  </button>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <ChartFrame title="Open queue by age" description="Age of cases still open. Select a cell to filter the queue."
      chart={grid(false)} table={grid(true)}
      aside={<span className="text-xs text-soc-muted num">{a.queue.open_total} open</span>} />
  );
}

export function ReviewTime({ a }: { a: Analytics }) {
  const rt = a.queue.review_time;
  return (
    <div className="rounded-md border border-soc-line bg-soc-panel p-4">
      <h3 className="text-sm font-semibold">Review time for disposed cases</h3>
      <p className="mt-0.5 text-xs text-soc-muted">Case creation to first analyst or customer disposition.</p>
      {rt.n === 0 ? <p className="mt-4 text-sm text-soc-muted">No disposed cases in this range.</p> : (
        <dl className="num mt-3 grid grid-cols-4 gap-3 text-sm">
          <div><dt className="text-xs text-soc-muted">Median</dt><dd className="text-lg font-semibold">{formatDuration(rt.p50_ms)}</dd></div>
          <div><dt className="text-xs text-soc-muted">90th pct</dt><dd className="text-lg font-semibold">{formatDuration(rt.p90_ms)}</dd></div>
          <div><dt className="text-xs text-soc-muted">Mean</dt><dd className="text-lg font-semibold">{formatDuration(rt.mean_ms)}</dd></div>
          <div><dt className="text-xs text-soc-muted">Sample</dt><dd className="text-lg font-semibold">n = {rt.n}</dd></div>
        </dl>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- quality and worker
export function QualityAndWorker({ a }: { a: Analytics }) {
  const q = a.model_quality;
  const w = a.worker;
  return (
    <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <div className="rounded-md border border-soc-line bg-soc-panel p-4">
        <h3 className="text-sm font-semibold">Measured signal quality</h3>
        <p className="mt-0.5 text-xs text-soc-muted">Stored flags compared with analyst adjudications. These are counts from reviewed cases, not model risk estimates.</p>
        {q.adjudicated_cases === 0 ? <p className="mt-4 text-sm text-soc-muted">Awaiting reviewed cases.</p> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr><Th>Signal</Th><Th>Revision</Th><Th right>TP</Th><Th right>FP</Th><Th right>TN</Th><Th right>FN</Th><Th right>Unscored</Th><Th right>Precision</Th><Th right>Recall</Th></tr></thead>
              <tbody className="num">
                {q.rows.map((r) => (
                  <tr key={`${r.signal}${r.revision}${r.n}`} className="border-t border-soc-line/60">
                    <td className="px-2 py-1">{r.signal.replace(/_/g, " ")}</td>
                    <td className="max-w-[10rem] truncate px-2 py-1 font-mono text-xs text-soc-muted" title={`${r.model_id ?? "—"} @ ${r.revision ?? "—"}`}>{r.revision ?? "unavailable"}</td>
                    <td className="px-2 py-1 text-right">{r.tp}</td><td className="px-2 py-1 text-right">{r.fp}</td>
                    <td className="px-2 py-1 text-right">{r.tn}</td><td className="px-2 py-1 text-right">{r.fn}</td>
                    <td className="px-2 py-1 text-right text-soc-muted">{r.abstain}</td>
                    <td className="px-2 py-1 text-right">{r.precision == null ? "—" : r.precision.toFixed(2)}</td>
                    <td className="px-2 py-1 text-right">{r.recall == null ? "—" : r.recall.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-soc-faint">{q.adjudicated_cases} adjudicated case{q.adjudicated_cases === 1 ? "" : "s"}. Small samples carry wide uncertainty.</p>
          </div>
        )}
      </div>
      <div className="rounded-md border border-soc-line bg-soc-panel p-4">
        <h3 className="text-sm font-semibold">SOC worker health</h3>
        <p className="mt-0.5 text-xs text-soc-muted">From the durable job table, so it stays accurate if the broker is down.</p>
        <dl className="num mt-3 grid grid-cols-3 gap-x-4 gap-y-3 text-sm">
          {([["Queued", w.queued], ["Running", w.leased], ["Completed", w.completed], ["Retries", w.retries], ["Failed", w.failed]] as const).map(([k, v]) => (
            <div key={k}><dt className="text-xs text-soc-muted">{k}</dt><dd className={`text-lg font-semibold ${k === "Failed" && v ? "text-soc-red" : ""}`}>{v}</dd></div>
          ))}
          <div><dt className="text-xs text-soc-muted">Oldest pending</dt><dd className={`text-lg font-semibold ${w.oldest_pending_age_ms && w.oldest_pending_age_ms > 60_000 ? "text-soc-amber" : ""}`}>{w.oldest_pending_age_ms == null ? "None" : formatDuration(w.oldest_pending_age_ms)}</dd></div>
        </dl>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- signal evidence (case scoped)
export function SignalChart({ evidence, onSelect }: { evidence: Evidence[]; onSelect: (id: string) => void }) {
  const cap = evidence.find((e) => e.kind === "capture_quality");
  const tr = evidence.find((e) => e.kind === "transcript");
  const voice = evidence.find((e) => e.kind === "voice_authenticity");
  const speech = evidence.find((e) => e.kind === "speech_content");
  const remark = evidence.find((e) => e.kind === "typed_remark");
  const [hover, setHover] = useState<string | null>(null);

  const dur = cap?.payload?.duration_ms ?? 0;
  const levels: number[] = cap?.payload?.levels_dbfs ?? [];
  const frame = cap?.payload?.frame_ms ?? 20;
  const pts: { offset_ms: number; window_ms: number; score: number }[] = voice?.payload?.points ?? [];
  const segs: { start_ms: number; end_ms: number; text: string }[] = tr?.payload?.segments ?? [];
  const W = 640, x = (ms: number) => 40 + (ms / Math.max(1, dur)) * (W - 50);

  const levelPath = useMemo(() => {
    if (!levels.length) return "";
    return levels.map((d, i) => `${i ? "L" : "M"}${x(i * frame).toFixed(1)},${(64 - Math.max(0, Math.min(1, (d + 70) / 70)) * 54).toFixed(1)}`).join("");
  }, [levels, frame, dur]);

  const status = (e?: Evidence) => !e ? "not produced" : e.status === "unavailable" ? `unavailable (${e.payload?.reason ?? "no reason"})` : e.status;

  const table = (
    <table className="w-full text-sm">
      <thead><tr><Th>Signal</Th><Th>Status</Th><Th right>Score</Th><Th>Scale</Th><Th>Model / revision</Th><Th>Evidence</Th></tr></thead>
      <tbody>
        {[cap, tr, voice, speech, remark].filter(Boolean).map((e) => (
          <tr key={e!.id} className="border-t border-soc-line/60">
            <td className="px-2 py-1">{e!.kind.replace(/_/g, " ")}</td>
            <td className="px-2 py-1">{e!.status}{e!.review_only && e!.status !== "unavailable" ? " · review-only" : ""}</td>
            <td className="num px-2 py-1 text-right">{e!.score ?? "—"}</td>
            <td className="px-2 py-1 text-xs text-soc-muted">{e!.score_scale ?? "—"}</td>
            <td className="px-2 py-1 font-mono text-xs">{e!.model_id ?? "—"}{e!.revision ? `@${e!.revision.slice(0, 10)}` : ""}</td>
            <td className="px-2 py-1"><button className="font-mono text-xs underline-offset-2 hover:underline" onClick={() => onSelect(e!.id)}>{e!.id}</button></td>
          </tr>
        ))}
        {pts.map((p) => (
          <tr key={p.offset_ms} className="border-t border-soc-line/60 text-soc-muted">
            <td className="px-2 py-1 pl-6">window {formatDuration(p.offset_ms)}</td><td className="px-2 py-1">uncalibrated</td>
            <td className="num px-2 py-1 text-right">{p.score.toFixed(3)}</td><td colSpan={3} />
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartFrame title="Signal evidence"
      description="Measured capture level, voice-authenticity windows and transcript segments over the recording. Gaps mean no model output."
      table={table}
      chart={
        <div className="space-y-3">
          {!cap ? <p className="text-sm text-soc-muted">No capture evidence stored for this payment.</p> : (
            <svg viewBox={`0 0 ${W} 150`} className="w-full" role="img" aria-label={`Recording ${formatDuration(dur)}; ${pts.length} voice windows; ${segs.length} transcript segments.`}>
              <text x="0" y="14" className="fill-soc-faint text-[10px]">level</text>
              <line x1="40" x2={W - 10} y1="64" y2="64" stroke="rgb(var(--ui-control))" />
              {levelPath && <path d={levelPath} fill="none" stroke="rgb(var(--ui-blue))" strokeWidth="1.2" />}
              <text x="0" y="92" className="fill-soc-faint text-[10px]">voice</text>
              <line x1="40" x2={W - 10} y1="100" y2="100" stroke="rgb(var(--ui-control))" strokeDasharray="2 3" />
              {voice?.status === "unavailable" && <text x="44" y="96" className="fill-soc-faint text-[10px]">model unavailable · {voice.payload?.reason}</text>}
              {pts.map((p) => (
                <g key={p.offset_ms} onMouseEnter={() => setHover(`${p.score}`)} onMouseLeave={() => setHover(null)}>
                  <rect x={x(p.offset_ms)} y={100 - p.score * 22} width={Math.max(2, x(p.offset_ms + p.window_ms) - x(p.offset_ms) - 2)} height={p.score * 22}
                        fill={p.score >= (voice?.payload?.threshold ?? 0.5) ? "rgb(var(--ui-red))" : "rgb(var(--ui-blue))"} opacity=".85"
                        className="cursor-pointer" onClick={() => voice && onSelect(voice.id)}><title>{`window ${p.offset_ms} ms: ${p.score}`}</title></rect>
                </g>
              ))}
              <text x="0" y="128" className="fill-soc-faint text-[10px]">speech</text>
              {segs.length === 0 && <text x="44" y="128" className="fill-soc-faint text-[10px]">{tr ? "no transcript segments" : "transcription unavailable"}</text>}
              {segs.map((s, i) => (
                <rect key={i} x={x(s.start_ms)} y={120} width={Math.max(2, x(s.end_ms) - x(s.start_ms))} height="10" rx="2" fill="rgb(var(--ui-amber))" opacity=".75"
                      className="cursor-pointer" onClick={() => tr && onSelect(tr.id)}><title>{s.text}</title></rect>
              ))}
              <text x="40" y="146" className="fill-soc-faint text-[10px] num">0s</text>
              <text x={W - 10} y="146" textAnchor="end" className="fill-soc-faint text-[10px] num">{(dur / 1000).toFixed(1)}s</text>
            </svg>
          )}
          {hover && <p className="text-xs text-soc-muted num">Window score {hover} (uncalibrated)</p>}
          <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            <div className="flex gap-2"><dt className="text-soc-muted">Voice authenticity</dt><dd>{status(voice)}{voice?.review_only && voice.status !== "unavailable" ? " · review-only" : ""}</dd></div>
            <div className="flex gap-2"><dt className="text-soc-muted">Spoken content</dt><dd>{status(speech)}</dd></div>
            <div className="flex gap-2"><dt className="text-soc-muted">Typed remark</dt><dd>{status(remark)}{remark?.score != null ? ` · ${remark.score}` : ""}</dd></div>
            <div className="flex gap-2"><dt className="text-soc-muted">Speech measured</dt><dd className="num">{formatDuration(cap?.payload?.voiced_ms)} of {formatDuration(dur)}</dd></div>
          </dl>
        </div>
      } />
  );
}
