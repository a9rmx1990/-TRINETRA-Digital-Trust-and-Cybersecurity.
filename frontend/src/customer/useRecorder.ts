import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { api, type CallStatus } from "./api";

export type RecPhase = "idle" | "requesting" | "denied" | "unsupported" | "recording" | "analyzing" | "ready"
  | "unusable" | "interrupted" | "error";

const MAX_MS = 45_000;

/**
 * Captures microphone audio after consent and streams 16 kHz mono PCM to the server.
 * Levels come only from samples the worklet actually delivered; nothing is simulated.
 */
export function useRecorder() {
  const [phase, setPhase] = useState<RecPhase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState<number[]>([]);
  const [call, setCall] = useState<CallStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const callIdRef = useRef<string | null>(null);
  const pending = useRef<Int16Array[]>([]);
  const sending = useRef<Promise<void>>(Promise.resolve());
  const startedAt = useRef(0);
  const timer = useRef<number | null>(null);
  const failed = useRef(false);

  const teardown = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ctxRef.current?.close().catch(() => undefined);
    ctxRef.current = null;
  }, []);

  useEffect(() => () => teardown(), [teardown]);

  const flush = useCallback(() => {
    const id = callIdRef.current;
    if (!id || !pending.current.length) return sending.current;
    const parts = pending.current;
    pending.current = [];
    const total = parts.reduce((n, p) => n + p.length, 0);
    const buf = new Int16Array(total);
    let o = 0;
    for (const p of parts) {
      buf.set(p, o);
      o += p.length;
    }
    sending.current = sending.current.then(() =>
      api.sendPcm(id, buf.buffer).then(() => undefined).catch((e: unknown) => {
        failed.current = true;
        setError(e instanceof ApiError ? e.message : "Upload interrupted.");
      }));
    return sending.current;
  }, []);

  const stop = useCallback(async () => {
    if (!callIdRef.current || !ctxRef.current) return;
    teardown();
    setPhase("analyzing");
    await flush();
    if (failed.current) {
      setPhase("interrupted");
      return;
    }
    try {
      const st = await api.finishCall(callIdRef.current);
      setCall(st);
      setPhase(st.usable ? "ready" : "unusable");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not finish the recording.");
      setPhase(e instanceof ApiError && e.code === "call_expired" ? "interrupted" : "error");
    }
  }, [flush, teardown]);

  const start = useCallback(async () => {
    setError(null);
    setLevels([]);
    setElapsed(0);
    setCall(null);
    failed.current = false;
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === "undefined") {
      setPhase("unsupported");
      return;
    }
    if (callIdRef.current && phase !== "ready") api.deleteCall(callIdRef.current).catch(() => undefined);
    setPhase("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch {
      setPhase("denied");
      return;
    }
    try {
      const c = await api.startCall();
      callIdRef.current = c.id;
      const ctx = new AudioContext();
      await ctx.audioWorklet.addModule("/pcm-worklet.js");
      const src = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "pcm-worklet");
      node.port.onmessage = (ev: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) => {
        pending.current.push(new Int16Array(ev.data.pcm));
        const db = 20 * Math.log10(ev.data.rms + 1e-9);
        setLevels((l) => [...l.slice(-119), Math.max(0, Math.min(1, (db + 60) / 60))]);
      };
      src.connect(node);
      // Keep the graph pulled without playing audio back.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      node.connect(mute).connect(ctx.destination);
      streamRef.current = stream;
      ctxRef.current = ctx;
      stream.getAudioTracks()[0]?.addEventListener("ended", () => {
        failed.current = true;
        setError("The microphone was disconnected.");
        stop();
      });
      startedAt.current = performance.now();
      setPhase("recording");
      timer.current = window.setInterval(() => {
        const e = performance.now() - startedAt.current;
        setElapsed(e);
        flush();
        if (e >= MAX_MS) stop();
      }, 500);
    } catch (e) {
      stream.getTracks().forEach((t) => t.stop());
      setError(e instanceof ApiError ? e.message : "Recording could not start.");
      setPhase("error");
    }
  }, [flush, phase, stop]);

  const reset = useCallback(() => {
    teardown();
    if (callIdRef.current && phase !== "ready") api.deleteCall(callIdRef.current).catch(() => undefined);
    callIdRef.current = null;
    setPhase("idle");
    setLevels([]);
    setElapsed(0);
    setCall(null);
    setError(null);
  }, [phase, teardown]);

  return { phase, elapsed, levels, call, error, start, stop, reset, maxMs: MAX_MS };
}
