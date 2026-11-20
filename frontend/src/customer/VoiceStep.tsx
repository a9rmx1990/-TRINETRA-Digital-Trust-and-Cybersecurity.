import { Mic, RotateCcw, Square, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { clockTime } from "../lib/format";
import { Notice, Spinner } from "./ui";
import type { useRecorder } from "./useRecorder";

type Rec = ReturnType<typeof useRecorder>;

const REASON: Record<string, string> = {
  silence: "We could not hear speech in that recording. Move somewhere quieter, hold the device closer and record again.",
  too_short: "That recording was too short. Speak for at least two seconds.",
  clipped: "The recording was too loud and distorted. Hold the device a little further away and record again.",
  no_audio: "No audio reached the bank. Check that the right microphone is selected and record again.",
};

/** Level history from real worklet RMS. One bar per 100 ms frame; empty until samples arrive. */
function LevelTrace({ levels, live }: { levels: number[]; live: boolean }) {
  const N = 120;
  const pad = N - levels.length;
  return (
    <div className="relative h-24 w-full overflow-hidden rounded-lg bg-canvas" aria-hidden="true">
      <svg viewBox={`0 0 ${N * 4} 96`} preserveAspectRatio="none" className="h-full w-full">
        <line x1="0" x2={N * 4} y1="48" y2="48" stroke="rgb(var(--ui-line))" strokeWidth="1" />
        {levels.map((v, i) => {
          const h = Math.max(1.5, v * 88);
          return <rect key={i} x={(pad + i) * 4 + 0.5} y={48 - h / 2} width="2.5" height={h} rx="1.2"
                       fill={i === levels.length - 1 && live ? "rgb(var(--ui-blue))" : "rgb(var(--ui-ink))"} opacity={live ? 0.35 + 0.65 * (i / levels.length) : 0.55} />;
        })}
      </svg>
      {live && levels.length === 0 && (
        <p className="absolute inset-0 grid place-items-center text-sm text-muted">Waiting for microphone audio…</p>
      )}
    </div>
  );
}

export function VoiceStep({ rec, onCancel, onContinue, contactName, amountText, purpose }: {
  rec: Rec; onCancel: () => void; onContinue: () => void; contactName: string; amountText: string; purpose?: string;
}) {
  const [consent, setConsent] = useState(false);
  const cid = useId();
  const { phase, call } = rec;
  const recording = phase === "recording";
  const busy = phase === "requesting" || phase === "analyzing";

  useEffect(() => {
    if (phase === "ready") setConsent(true);
  }, [phase]);

  return (
    <div className="workspace-panel space-y-5 p-4 sm:p-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold text-ink">Confirm by voice</h2>
        <p className="max-w-[60ch] text-base text-[#3A4458]">
          Say who you’re requesting money from and why. For example: “I’m requesting {amountText || "this amount"} from {contactName || "my contact"} for {purpose?.trim() ? purpose.trim().replace(/[.]$/, "").toLowerCase() : "rent"}.”
          The sandbox screens the recording for signs of pressure.
        </p>
      </div>

      <details className="group rounded-md border border-line bg-white px-3.5 py-2.5 text-sm text-[#3A4458]">
        <summary className="cursor-pointer font-semibold text-ink">How the recording is used</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Audio streams to the bank only while you record and is discarded once screening finishes.</li>
          <li>The sandbox keeps measured results (speech duration, transcript if available, screening scores) with this request.</li>
          <li>An unused recording expires after 10 minutes. You can cancel at any time.</li>
        </ul>
      </details>

      <label htmlFor={cid} className="flex items-start gap-3 text-base text-ink">
        <input id={cid} type="checkbox" className="mt-1 h-4 w-4 rounded border-line text-primary focus:ring-primary"
               checked={consent} disabled={recording || busy || phase === "ready"} onChange={(e) => setConsent(e.target.checked)} />
        <span>I agree to voice screening for this request.</span>
      </label>

      <div className="rounded-lg border border-line bg-white p-4 sm:p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold" aria-live="polite">
            {recording ? (
              <><span className="rec-dot h-2.5 w-2.5 rounded-full bg-bad" aria-hidden />Recording</>
            ) : phase === "analyzing" ? (
              <><Spinner />Checking the recording</>
            ) : phase === "ready" ? (
              <span className="text-ok">Recording accepted</span>
            ) : (
              <span className="text-muted">Microphone off</span>
            )}
          </div>
          <p className="num text-2xl font-semibold tracking-tight text-ink" aria-label={`Elapsed ${Math.floor(rec.elapsed / 1000)} seconds`}>
            {clockTime(rec.elapsed)}<span className="ml-1 text-sm font-normal text-muted">/ {clockTime(rec.maxMs)}</span>
          </p>
        </div>
        <LevelTrace levels={rec.levels} live={recording} />
        <div className="mt-4 flex flex-wrap gap-2">
          {recording ? (
            <button type="button" className="btn-primary" onClick={rec.stop}><Square className="h-4 w-4" aria-hidden />Stop</button>
          ) : phase === "ready" || phase === "unusable" || phase === "interrupted" || phase === "error" ? (
            <button type="button" className="btn-secondary" onClick={rec.start} disabled={!consent}>
              <RotateCcw className="h-4 w-4" aria-hidden />Retry recording
            </button>
          ) : (
            <button type="button" className="btn-primary" onClick={rec.start} disabled={!consent || busy}>
              {busy ? <Spinner /> : <Mic className="h-4 w-4" aria-hidden />}Start microphone
            </button>
          )}
          <button type="button" className="btn-quiet text-muted hover:bg-[#EEF0F4]" onClick={onCancel} disabled={busy}>
            <X className="h-4 w-4" aria-hidden />Cancel request
          </button>
        </div>
      </div>

      {phase === "denied" && (
        <Notice tone="warn" title="Microphone access is blocked">
          Your request details are saved. To continue, allow microphone access for this site in your browser’s address bar
          or site settings, then choose Start microphone again.
        </Notice>
      )}
      {phase === "unsupported" && (
        <Notice tone="warn" title="This browser cannot record audio">Open the sandbox in a current version of Chrome, Edge, Firefox or Safari.</Notice>
      )}
      {phase === "unusable" && call && (
        <Notice tone="warn" title="Record again">{REASON[call.quality_reason ?? ""] ?? "The recording could not be used."}</Notice>
      )}
      {(phase === "interrupted" || phase === "error") && (
        <Notice tone="bad" title="Recording interrupted">{rec.error ?? "The recording stopped unexpectedly."} Record again to continue.</Notice>
      )}
      {phase === "ready" && call && call.language_supported === false && (
        <Notice tone="info" title="Recorded, but your language could not be screened automatically">
          The recording is fine. Because automatic screening does not cover {call.language ? `this language (${call.language})` : "this language"}, the bank may ask for an extra verification step.
        </Notice>
      )}
      {phase === "ready" && call && call.transcript_status == null && call.language_supported !== false && (
        <p className="text-sm text-muted">Recorded {Math.round(call.voiced_ms / 100) / 10}s of speech.</p>
      )}

      <div className="flex justify-end border-t border-line pt-4">
        <button type="button" className="btn-primary" disabled={phase !== "ready" || !call?.usable} onClick={onContinue}>
          Review request
        </button>
      </div>
    </div>
  );
}
