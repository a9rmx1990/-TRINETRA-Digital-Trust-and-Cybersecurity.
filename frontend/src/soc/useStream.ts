import { useEffect, useRef, useState } from "react";
import { soc, type Notice } from "./api";

export type ConnState = "connecting" | "live" | "reconnecting" | "offline" | "unauthorized";

/**
 * Committed-change notices over WebSocket, resumed from the last processed delivery cursor.
 * Duplicate notices (same or older cursor) are dropped, so they cannot duplicate rows.
 */
export function useStream(onNotices: (n: Notice[]) => void) {
  const [state, setState] = useState<ConnState>("connecting");
  const cursor = useRef<number>(Number(sessionStorage.getItem("trinetra.soc.cursor") || 0));
  const cb = useRef(onNotices);
  cb.current = onNotices;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: number | undefined;
    let batch: Notice[] = [];
    let flushT: number | undefined;

    const flush = () => {
      flushT = undefined;
      if (batch.length) {
        const b = batch;
        batch = [];
        cb.current(b);
      }
    };

    const connect = () => {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/v2/soc/stream`);
      ws.onopen = () => ws?.send(JSON.stringify({ type: "auth", token: soc.token(), after: cursor.current }));
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.type === "ready") { attempt = 0; setState("live"); return; }
        if (m.type === "error") { setState(m.code === "unauthenticated" || m.code === "expired" ? "unauthorized" : "offline"); closed = true; return; }
        if (m.type === "notice") {
          if (m.cursor <= cursor.current) return; // duplicate or replayed notice
          cursor.current = m.cursor;
          sessionStorage.setItem("trinetra.soc.cursor", String(m.cursor));
          batch.push({ cursor: m.cursor, case_id: m.case_id, case_version: m.case_version, event: m.event, created_ms: m.created_ms });
          flushT ??= window.setTimeout(flush, 150);
        }
      };
      ws.onclose = () => {
        if (closed) return;
        attempt += 1;
        setState(attempt > 4 ? "offline" : "reconnecting");
        timer = window.setTimeout(connect, Math.min(15_000, 500 * 2 ** attempt));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearTimeout(flushT);
      ws?.close();
    };
  }, []);

  return { state, cursor };
}
