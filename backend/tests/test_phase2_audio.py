import time
import base64
import numpy as np
import pytest
from app.engines.audio_engine import AudioForensicsEngine
from app.schemas import AcousticDiagnostics

@pytest.fixture
def engine():
    return AudioForensicsEngine(sample_rate=16000)

@pytest.fixture
def authentic_audio():
    return AudioForensicsEngine.generate_authentic_sample(duration_sec=2.0)

@pytest.fixture
def synthetic_audio():
    return AudioForensicsEngine.generate_synthetic_sample(duration_sec=2.0)

# ============================================================================
# 1. Forensic Discrimination Tests
# ============================================================================

def test_authentic_speech_produces_low_risk(engine, authentic_audio):
    """Authentic voice must exhibit natural formant roll-off and score low risk (< 35)."""
    score, diagnostics, reasons = engine.analyze(authentic_audio)
    
    assert score < 35.0, f"Authentic voice scored unexpectedly high: {score}"
    assert not diagnostics.is_synthetic
    assert diagnostics.confidence < 0.35
    assert diagnostics.high_freq_ratio < 0.15, f"High frequency ratio too high for natural voice: {diagnostics.high_freq_ratio}"
    assert any("biological vocal tract" in r.lower() or "harmonics" in r.lower() for r in reasons)

def test_synthetic_vocoder_detected_with_high_risk(engine, synthetic_audio):
    """Neural vocoder artifacts must be flagged as synthetic with high risk score (>= 70)."""
    score, diagnostics, reasons = engine.analyze(synthetic_audio)
    
    assert score >= 70.0, f"Synthetic audio missed; score too low: {score}"
    assert diagnostics.is_synthetic is True
    assert diagnostics.confidence >= 0.70
    assert diagnostics.spectral_flatness > 0.03
    assert diagnostics.high_freq_ratio > 0.15
    assert len(reasons) > 0

# ============================================================================
# 2. Performance & Latency SLA (< 50ms for 2-second audio)
# ============================================================================

def test_dsp_execution_latency_under_50ms(engine, synthetic_audio):
    """Audio feature extraction and classification must run well under 50ms."""
    # Warmup
    engine.analyze(synthetic_audio)
    
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        engine.analyze(synthetic_audio)
        dt = (time.perf_counter() - t0) * 1000.0  # ms
        times.append(dt)
        
    avg_latency = np.mean(times)
    max_latency = np.max(times)
    print(f"\n[Acoustic Engine Benchmark] Average: {avg_latency:.2f}ms, Max: {max_latency:.2f}ms")
    assert avg_latency < 50.0, f"Average latency exceeded 50ms SLA: {avg_latency:.2f}ms"
    assert max_latency < 80.0

# ============================================================================
# 3. Base64 & Format Parsing Tests
# ============================================================================

def test_base64_encoded_audio_handling(engine, synthetic_audio):
    """Engine must accept base64 strings and yield identical results to raw bytes."""
    b64_str = base64.b64encode(synthetic_audio).decode("ascii")
    score_b64, diag_b64, _ = engine.analyze(b64_str)
    score_raw, diag_raw, _ = engine.analyze(synthetic_audio)
    
    assert score_b64 == score_raw
    assert diag_b64.is_synthetic == diag_raw.is_synthetic

# ============================================================================
# 4. Resilience & Edge Cases
# ============================================================================

def test_none_and_empty_inputs(engine):
    """Empty or None audio must not raise exceptions and return zero score."""
    for empty_input in [None, b"", "", "invalid_base64_???"]:
        score, diag, reasons = engine.analyze(empty_input)
        assert score == 0.0
        assert diag.is_synthetic is False
        assert len(reasons) > 0

def test_pure_silence_input(engine):
    """Pure silence array must be flagged as silent without division by zero."""
    silence = np.zeros(16000, dtype=np.int16).tobytes()
    score, diag, reasons = engine.analyze(silence)
    assert score == 0.0
    assert diag.is_synthetic is False

def test_corrupted_garbage_bytes(engine):
    """Corrupted non-WAV headers must fall back gracefully to raw PCM or return safe score."""
    garbage = b"\x00\xFF" * 100
    score, diag, _ = engine.analyze(garbage)
    assert 0.0 <= score <= 100.0

def test_diagnostics_feature_bounds(engine, synthetic_audio):
    """Acoustic feature values must strictly respect physical and mathematical bounds."""
    _, diag, _ = engine.analyze(synthetic_audio)
    assert 0.0 <= diag.confidence <= 1.0
    assert 0.0 <= diag.high_freq_ratio <= 1.0
    assert 0.0 <= diag.spectral_rolloff <= 8000.0
    assert 0.0 <= diag.spectral_entropy <= 1.0

# ============================================================================
# 5. In-Memory Transcode & Audio Policy Role Verification
# ============================================================================

def test_webm_container_transcode_resilience(engine, authentic_audio, synthetic_audio):
    """Transcoded WebM containers must be decoded in-memory and correctly classified."""
    import io
    import av

    # Create in-memory WebM Opus container from authentic audio
    buf_in = io.BytesIO(authentic_audio)
    container_in = av.open(buf_in)
    buf_out = io.BytesIO()
    container_out = av.open(buf_out, mode='w', format='webm')
    stream_out = container_out.add_stream('opus', rate=16000)

    for frame in container_in.decode(audio=0):
        for packet in stream_out.encode(frame):
            container_out.mux(packet)
    for packet in stream_out.encode(None):
        container_out.mux(packet)
    container_out.close()

    webm_bytes = buf_out.getvalue()
    score, diag, reasons = engine.analyze(webm_bytes)

    assert score < 35.0, f"WebM authentic voice scored too high: {score}"
    assert diag.is_synthetic is False

def test_audio_metric_decision_influence():
    """Acoustic score must actively drive HOLD (>=85), STEP_UP (>=50), and ALLOW verification (<=15)."""
    from app.engines.policy_engine import PolicyDecisionEngine
    from app.schemas import AcousticDiagnostics

    pe = PolicyDecisionEngine()

    # 1. Extreme voice clone forces HOLD
    d_hold, risk_hold, r_hold, _ = pe.evaluate(
        acoustic_score=90.0,
        graph_score=10.0,
        nlp_score=0.0,
        reasons_audio=["Acoustic clone artifacts."],
        reasons_graph=[],
        reasons_nlp=[]
    )
    assert d_hold == "HOLD"
    assert risk_hold >= 75.0
    assert any("HIGH-PRIORITY OVERRIDE" in r for r in r_hold)

    # 2. Moderate voice anomaly forces at least STEP_UP
    d_step, risk_step, r_step, _ = pe.evaluate(
        acoustic_score=55.0,
        graph_score=0.0,
        nlp_score=0.0,
        reasons_audio=["Acoustic anomaly."],
        reasons_graph=[],
        reasons_nlp=[]
    )
    assert d_step in ("STEP_UP", "HOLD")
    assert risk_step >= 35.0

    # 3. Authentic voice confirmed with positive note
    d_allow, risk_allow, r_allow, _ = pe.evaluate(
        acoustic_score=5.0,
        graph_score=10.0,
        nlp_score=0.0,
        reasons_audio=["Harmonics natural."],
        reasons_graph=[],
        reasons_nlp=[]
    )
    assert d_allow == "ALLOW"
    assert any("Acoustic authorization verified" in r for r in r_allow)
