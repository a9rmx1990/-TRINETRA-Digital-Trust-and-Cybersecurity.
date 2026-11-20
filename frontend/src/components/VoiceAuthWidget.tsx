/**
 * VoiceAuthWidget — Minimalist voice verification input (OLED dark)
 */
import { useState, useRef } from 'react';
import { Mic, MicOff, CheckCircle2, AlertCircle, Trash2 } from 'lucide-react';

interface Props {
  onChange: (b64: string | null) => void;
  selected: string | null;
}

type RecordState = 'idle' | 'recording' | 'done' | 'error';

export default function VoiceAuthWidget({ onChange, selected }: Props) {
  const [recordState, setRecordState] = useState<RecordState>('idle');
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function startRecording() {
    setRecordState('recording');
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      mediaRef.current = mr;
      mr.ondataavailable = e => chunksRef.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const ab = await blob.arrayBuffer();
        const b64 = btoa(String.fromCharCode(...new Uint8Array(ab)));
        onChange(b64);
        setRecordState('done');
      };
      mr.start();
      setTimeout(() => { if (mr.state === 'recording') mr.stop(); }, 3000);
    } catch {
      setRecordState('error');
    }
  }

  function stopRecording() {
    mediaRef.current?.stop();
  }

  function clearAudio() {
    onChange(null);
    setRecordState('idle');
  }

  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.08)',
      }}
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.5)' }}>
          <Mic size={12} className="text-indigo-400" />
          <span>Voice Biometric</span>
        </div>
        {selected && (
          <button
            onClick={clearAudio}
            type="button"
            className="flex items-center gap-1 text-xs transition-colors cursor-pointer"
            style={{ color: 'rgba(148,163,184,0.4)' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = '#fb7185'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = 'rgba(148,163,184,0.4)'; }}
          >
            <Trash2 size={11} />
            Clear
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={recordState === 'recording' ? stopRecording : startRecording}
          className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-medium transition-all shadow-sm cursor-pointer ${
            recordState === 'recording' ? 'hold-pulse' : ''
          }`}
          style={recordState === 'recording' ? {
            background: 'rgba(244,63,94,0.15)',
            border: '1px solid rgba(244,63,94,0.3)',
            color: '#fb7185',
          } : {
            background: 'rgba(99,102,241,0.12)',
            border: '1px solid rgba(99,102,241,0.25)',
            color: '#a5b4fc',
          }}
        >
          {recordState === 'recording' ? <MicOff size={12} /> : <Mic size={12} />}
          {recordState === 'recording' ? 'Listening (3s)…' : 'Record Verification Call'}
        </button>

        {recordState === 'done' && (
          <div
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium"
            style={{
              background: 'rgba(16,185,129,0.1)',
              border: '1px solid rgba(16,185,129,0.2)',
              color: '#34d399',
            }}
          >
            <CheckCircle2 size={11} />
            Voice captured
          </div>
        )}

        {recordState === 'error' && (
          <div
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium"
            style={{
              background: 'rgba(244,63,94,0.1)',
              border: '1px solid rgba(244,63,94,0.2)',
              color: '#fb7185',
            }}
          >
            <AlertCircle size={11} />
            Microphone permission required
          </div>
        )}

        {recordState === 'idle' && !selected && (
          <span className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>
            Optional 3s sample · LFCC spectral engine
          </span>
        )}
      </div>
    </div>
  );
}
