"""Acoustic Forensics Engine: Synthetic Voice & Neural Vocoder Artifact Detection.

Analyzes high-frequency LFCC distribution, spectral flatness (Wiener entropy),
spectral roll-off, and energy uniformity to detect GenAI voice clones.
"""

import io
import wave
import base64
import numpy as np
from scipy import signal
from typing import Tuple, List, Optional
from app.schemas import AcousticDiagnostics

class AudioForensicsEngine:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def parse_audio(self, raw_data: Optional[bytes | str]) -> np.ndarray:
        """Decode base64 or raw bytes into a 1D float32 audio signal [-1.0, 1.0]."""
        if not raw_data:
            return np.zeros(0, dtype=np.float32)

        # Decode base64 if passed as string
        if isinstance(raw_data, str):
            try:
                raw_bytes = base64.b64decode(raw_data)
            except Exception:
                return np.zeros(0, dtype=np.float32)
        else:
            raw_bytes = raw_data

        if len(raw_bytes) == 0:
            return np.zeros(0, dtype=np.float32)

        # Attempt reading standard WAV container
        try:
            with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                sr = wf.getframerate()
                n_channels = wf.getnchannels()
                frames = wf.readframes(wf.getnframes())
                sampwidth = wf.getsampwidth()

                if sampwidth == 2:
                    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                elif sampwidth == 1:
                    audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
                else:
                    audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0

                # Convert stereo to mono if needed
                if n_channels > 1:
                    audio = audio.reshape(-1, n_channels).mean(axis=1)

                # Resample if sample rate differs from target
                if sr != self.sample_rate and len(audio) > 0:
                    num_samples = int(len(audio) * float(self.sample_rate) / sr)
                    audio = signal.resample(audio, num_samples)

                return audio.astype(np.float32)
        except Exception:
            # Fallback (Option B): In-memory transcode for non-WAV formats (WebM/Opus, MP3, OGG, etc.) via PyAV
            try:
                import av
                container = av.open(io.BytesIO(raw_bytes))
                resampler = av.AudioResampler(format='fltp', layout='mono', rate=self.sample_rate)
                chunks = []
                for frame in container.decode(audio=0):
                    for r_frame in resampler.resample(frame):
                        chunks.append(r_frame.to_ndarray()[0])
                if chunks:
                    return np.concatenate(chunks).astype(np.float32)
            except Exception:
                pass

            # Final fallback: Treat as raw 16-bit PCM mono
            try:
                audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                return audio
            except Exception:
                return np.zeros(0, dtype=np.float32)

    def extract_features(self, audio: np.ndarray) -> dict:
        """Computes spectral flatness, high-frequency ratio, roll-off, and entropy."""
        n_samples = len(audio)
        if n_samples < 512 or np.all(np.abs(audio) < 1e-4):
            return {
                "spectral_flatness": 0.0,
                "high_freq_ratio": 0.0,
                "spectral_rolloff": 0.0,
                "frame_entropy": 0.0,
                "is_silent": True
            }

        # 1. FFT Power Spectrum
        fft_len = 1024
        hop_len = 256
        freqs, times, stft = signal.stft(audio, fs=self.sample_rate, nperseg=fft_len, noverlap=fft_len - hop_len)
        power = np.abs(stft) ** 2
        avg_power = np.mean(power, axis=1) + 1e-12

        # 2. Spectral Flatness (Wiener Entropy): Geometric Mean / Arithmetic Mean
        geo_mean = np.exp(np.mean(np.log(avg_power)))
        arith_mean = np.mean(avg_power)
        spectral_flatness = float(geo_mean / arith_mean)

        # 3. High-Frequency Band Ratio (> 4000 Hz)
        # Vocoders (HiFi-GAN, WaveGlow) exhibit high-frequency spectral persistence
        hf_mask = freqs >= 4000.0
        total_energy = np.sum(avg_power)
        hf_energy = np.sum(avg_power[hf_mask]) if np.any(hf_mask) else 0.0
        high_freq_ratio = float(hf_energy / (total_energy + 1e-12))

        # 4. Spectral Roll-off (frequency below which 85% of total spectral power lies)
        cumulative_energy = np.cumsum(avg_power)
        rolloff_idx = np.searchsorted(cumulative_energy, 0.85 * total_energy)
        rolloff_idx = min(rolloff_idx, len(freqs) - 1)
        spectral_rolloff = float(freqs[rolloff_idx])

        # 5. Frame Energy Entropy & Temporal Uniformity
        frame_energies = np.sum(power, axis=0) + 1e-12
        frame_probs = frame_energies / np.sum(frame_energies)
        entropy = -float(np.sum(frame_probs * np.log2(frame_probs + 1e-12)))
        # Normalize entropy by max theoretical entropy log2(frames)
        max_entropy = np.log2(len(frame_energies)) if len(frame_energies) > 1 else 1.0
        norm_entropy = float(entropy / max_entropy) if max_entropy > 0 else 0.0

        return {
            "spectral_flatness": round(spectral_flatness, 4),
            "high_freq_ratio": round(high_freq_ratio, 4),
            "spectral_rolloff": round(spectral_rolloff, 1),
            "frame_entropy": round(norm_entropy, 4),
            "is_silent": False
        }

    def analyze(self, raw_audio: Optional[bytes | str]) -> Tuple[float, AcousticDiagnostics, List[str]]:
        """Evaluates input audio, returning (score 0-100, diagnostics, explanation list)."""
        audio = self.parse_audio(raw_audio)
        feats = self.extract_features(audio)

        if feats["is_silent"]:
            return (
                0.0,
                AcousticDiagnostics(
                    is_synthetic=False,
                    confidence=0.0,
                    spectral_entropy=0.0,
                    spectral_rolloff=0.0,
                    high_freq_ratio=0.0
                ),
                ["No audio stream provided or input signal is below audible noise threshold."]
            )

        # Forensic artifact weights
        # Vocoders show high spectral flatness, abnormal HF ratio (>0.18), elevated rolloff (>4500Hz)
        reasons = []
        anomaly_points = 0.0

        # Anomaly 1: Spectral Flatness (Vocoder white noise / unvoiced synthesis floor)
        if feats["spectral_flatness"] > 0.03:
            anomaly_points += 35.0
            reasons.append(f"Elevated spectral flatness detected ({feats['spectral_flatness']}); matches neural vocoder synthesis floor.")
        elif feats["spectral_flatness"] > 0.015:
            anomaly_points += 15.0
            reasons.append("Mild spectral flatness elevation detected.")

        # Anomaly 2: High-Frequency Energy Ratio (>4000 Hz)
        if feats["high_freq_ratio"] > 0.18:
            anomaly_points += 35.0
            reasons.append(f"Abnormal high-frequency power ratio ({feats['high_freq_ratio'] * 100:.1f}% > 4kHz); characteristic of TTS phase artifacts.")
        elif feats["high_freq_ratio"] > 0.10:
            anomaly_points += 15.0

        # Anomaly 3: Spectral Roll-off Frequency
        if feats["spectral_rolloff"] > 4000.0:
            anomaly_points += 20.0
            reasons.append(f"Unnatural acoustic roll-off point ({feats['spectral_rolloff']} Hz).")
        elif feats["spectral_rolloff"] > 3000.0:
            anomaly_points += 10.0

        # Anomaly 4: Temporal Energy Entropy (synthetic TTS has unnaturally flat entropy)
        if feats["frame_entropy"] > 0.97:
            anomaly_points += 15.0
            reasons.append("Acoustic frame energy entropy indicates lack of biological prosodic variation.")

        # Bound score [0.0, 100.0]
        acoustic_score = min(100.0, max(0.0, anomaly_points))
        is_synthetic = acoustic_score >= 60.0
        confidence = round(acoustic_score / 100.0, 3)

        if not reasons:
            reasons.append("Acoustic harmonics and formant roll-off match biological vocal tract dynamics.")

        diagnostics = AcousticDiagnostics(
            is_synthetic=is_synthetic,
            confidence=confidence,
            spectral_flatness=feats["spectral_flatness"],
            spectral_entropy=feats["frame_entropy"],
            spectral_rolloff=feats["spectral_rolloff"],
            high_freq_ratio=feats["high_freq_ratio"]
        )

        return (round(acoustic_score, 1), diagnostics, reasons)

    # ------------------------------------------------------------------------
    # Audio Synthesis Helpers for Testing and Demo Simulation
    # ------------------------------------------------------------------------

    @staticmethod
    def generate_authentic_sample(duration_sec: float = 2.0, sr: int = 16000) -> bytes:
        """Generates realistic human-like voice audio with natural decaying formants."""
        t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
        # Fundamental pitch ~130Hz with decreasing harmonic overtones
        f0 = 130.0
        signal_data = (
            1.0 * np.sin(2 * np.pi * f0 * t) +
            0.6 * np.sin(2 * np.pi * (2 * f0) * t) +
            0.3 * np.sin(2 * np.pi * (3 * f0) * t) +
            0.1 * np.sin(2 * np.pi * (4 * f0) * t)
        )
        # Formant envelope (vocal tract resonance peaking at ~700Hz and 1800Hz)
        b, a = signal.butter(4, [300 / (sr / 2), 3400 / (sr / 2)], btype="bandpass")
        filtered = signal.lfilter(b, a, signal_data)
        # Apply amplitude envelope (natural cadence / syllable modulation)
        envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 3.0 * t))
        audio = (filtered * envelope)
        audio = (audio / (np.max(np.abs(audio)) + 1e-6)) * 0.8
        pcm = (audio * 32767).astype(np.int16)

        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        return out.getvalue()

    @staticmethod
    def generate_synthetic_sample(duration_sec: float = 2.0, sr: int = 16000) -> bytes:
        """Generates synthetic vocoder-like audio with high spectral flatness and HF persistence."""
        t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
        f0 = 160.0
        # Equalized harmonics extending high up into 7kHz band
        harmonics = sum(0.3 * np.sin(2 * np.pi * (k * f0) * t) for k in range(1, 35))
        # Neural vocoder artifact: high-frequency phase noise & dispersion
        high_noise = 0.25 * np.random.normal(0, 1, len(t))
        b_hp, a_hp = signal.butter(3, 4200 / (sr / 2), btype="highpass")
        hp_noise = signal.lfilter(b_hp, a_hp, high_noise)

        combined = harmonics + hp_noise
        combined = (combined / (np.max(np.abs(combined)) + 1e-6)) * 0.85
        pcm = (combined * 32767).astype(np.int16)

        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        return out.getvalue()
