import { useEffect, useRef, useState } from 'react';
import { api, post } from '../sandbox';

type Session = { session_id: string; webrtc: boolean; ice_servers: RTCIceServer[] };
type Status = { state: string; received_ms: number; coverage_ms?: number };

function waitForIce(peer: RTCPeerConnection) {
  return new Promise<void>((resolve, reject) => {
    if (peer.iceGatheringState === 'complete') return resolve();
    const timeout = window.setTimeout(() => {
      peer.removeEventListener('icegatheringstatechange', check);
      reject(new Error('WebRTC network setup timed out.'));
    }, 8000);
    function check() {
      if (peer.iceGatheringState !== 'complete') return;
      clearTimeout(timeout);
      peer.removeEventListener('icegatheringstatechange', check);
      resolve();
    }
    peer.addEventListener('icegatheringstatechange', check);
  });
}

export function useCall(key: string) {
  const [state, setState] = useState('idle');
  const [transport, setTransport] = useState('');
  const [error, setError] = useState('');
  const [id, setId] = useState<string>();
  const current = useRef<{
    sid?: string; mic?: MediaStream; peer?: RTCPeerConnection; context?: AudioContext;
    pcm?: AudioWorkletNode; flushed?: () => void; queue: Promise<unknown>; waiting: number; failed: boolean;
  } | null>(null);

  useEffect(() => () => {
    const call = current.current;
    current.current = null;
    if (!call) return;
    stopHardware(call);
    if (call.sid) void api('/calls/' + call.sid, key, { method: 'DELETE' }).catch(() => {});
  }, [key]);

  function stopHardware(call: NonNullable<typeof current.current>) {
    call.peer?.close();
    call.mic?.getTracks().forEach(track => track.stop());
    if (call.context && call.context.state !== 'closed') void call.context.close().catch(() => {});
  }

  async function start() {
    const previous = current.current;
    if (previous?.sid) void api('/calls/' + previous.sid, key, { method: 'DELETE' }).catch(() => {});
    const call: NonNullable<typeof current.current> = { queue: Promise.resolve(), waiting: 0, failed: false };
    current.current = call;
    setId(undefined);
    setError('');
    setState('connecting');
    try {
      if (!navigator.mediaDevices) throw new Error('Open the sandbox on localhost or HTTPS to use the microphone.');
      call.mic = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      if (current.current !== call) return stopHardware(call);
      const session = await api<Session>('/calls', key, post({ consent: true }));
      call.sid = session.session_id;
      if (current.current !== call) {
        await api('/calls/' + call.sid, key, { method: 'DELETE' });
        return stopHardware(call);
      }
      setId(call.sid);
      if (session.webrtc) {
        call.peer = new RTCPeerConnection({ iceServers: session.ice_servers });
        call.mic.getTracks().forEach(track => call.peer?.addTrack(track, call.mic!));
        await call.peer.setLocalDescription(await call.peer.createOffer());
        await waitForIce(call.peer);
        const answer = await api<RTCSessionDescriptionInit>('/calls/' + call.sid + '/offer', key,
          post({ sdp: call.peer.localDescription?.sdp }));
        await call.peer.setRemoteDescription(answer);
        call.peer.onconnectionstatechange = () => {
          if (current.current !== call || call.peer?.connectionState !== 'failed') return;
          if (call.sid) void api('/calls/' + call.sid, key, { method: 'DELETE' }).catch(() => {});
          stopHardware(call);
          setState('disconnected');
        };
        setTransport('WebRTC');
      } else {
        const context = new AudioContext({ sampleRate: 16000 });
        call.context = context;
        if (context.sampleRate !== 16000) throw new Error('This browser cannot capture at the sandbox audio rate.');
        await context.audioWorklet.addModule('/pcm-worklet.js');
        if (current.current !== call) return stopHardware(call);
        const node = new AudioWorkletNode(context, 'pcm-capture');
        call.pcm = node;
        node.port.onmessage = ({ data }: MessageEvent<ArrayBuffer | null>) => {
          if (!data) return call.flushed?.();
          if (call.waiting >= 4 || call.failed) {
            call.failed = true;
            return;
          }
          call.waiting++;
          call.queue = call.queue.then(() => call.failed ? undefined : api('/calls/' + call.sid + '/pcm', key, {
            method: 'POST', body: data, headers: { 'Content-Type': 'application/octet-stream' },
          })).catch(() => { call.failed = true; }).finally(() => { call.waiting--; });
        };
        context.createMediaStreamSource(call.mic).connect(node).connect(context.destination);
        await context.resume();
        setTransport('live PCM');
      }
      if (current.current === call) setState('capturing');
    } catch (ex) {
      stopHardware(call);
      if (current.current === call) {
        setError(ex instanceof DOMException && ex.name === 'NotAllowedError' ?
          'Microphone access was blocked. Allow access in your browser and try again.' :
          ex instanceof Error ? ex.message : 'Microphone session failed.');
        setState('error');
      }
    }
  }

  async function finish() {
    const call = current.current;
    if (!call?.sid) return;
    setState('processing');
    try {
      if (call.pcm) {
        await new Promise<void>(resolve => {
          const timer = window.setTimeout(() => { call.failed = true; resolve(); }, 500);
          call.flushed = () => { clearTimeout(timer); resolve(); };
          call.pcm?.port.postMessage('flush');
        });
        await call.queue;
      }
      if (call.failed) {
        await api('/calls/' + call.sid, key, { method: 'DELETE' }).catch(() => {});
        if (current.current === call) setState('disconnected');
        return;
      }
      const result = await api<Status>('/calls/' + call.sid + '/finish', key, post());
      if (current.current === call) setState(result.state);
    } catch (ex) {
      if (current.current === call) {
        setError(ex instanceof Error ? ex.message : 'Call could not be finalized.');
        setState('error');
      }
    } finally {
      stopHardware(call);
    }
  }

  async function clear() {
    const call = current.current;
    current.current = null;
    stopHardware(call ?? { queue: Promise.resolve(), waiting: 0, failed: false });
    setId(undefined);
    setState('idle');
    setError('');
    if (call?.sid) {
      await api('/calls/' + call.sid, key, { method: 'DELETE' }).catch(() => {});
    }
  }

  return { state, id, transport, error, start, finish, clear };
}
