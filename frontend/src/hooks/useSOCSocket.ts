/**
 * useSOCSocket — WebSocket hook for SOC live stream
 * Connects ws://localhost:8000/ws/soc-stream with 2s auto-reconnect
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import type { SOCEvent, CytoscapeGraph } from '../types';

const WS_URL = 'ws://localhost:8000/ws/soc-stream';
const MAX_EVENTS = 50;
const RECONNECT_DELAY = 2000;

export interface SOCSocketState {
  events: SOCEvent[];
  connected: boolean;
  latestGraph: CytoscapeGraph | null;
}

export function useSOCSocket(): SOCSocketState {
  const [events, setEvents] = useState<SOCEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [latestGraph, setLatestGraph] = useState<CytoscapeGraph | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  const connect = useCallback(() => {
    if (unmountedRef.current) return;
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmountedRef.current) return ws.close();
      setConnected(true);
    };

    ws.onmessage = (e: MessageEvent) => {
      try {
        const ev: SOCEvent = JSON.parse(e.data as string);
        setEvents(prev => [ev, ...prev].slice(0, MAX_EVENTS));
        if (ev.cytoscape_subgraph) setLatestGraph(ev.cytoscape_subgraph);
      } catch {
        /* ignore malformed frames */
      }
    };

    ws.onerror = () => ws.close();

    ws.onclose = () => {
      setConnected(false);
      if (!unmountedRef.current) {
        timerRef.current = setTimeout(connect, RECONNECT_DELAY);
      }
    };
  }, []);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { events, connected, latestGraph };
}
