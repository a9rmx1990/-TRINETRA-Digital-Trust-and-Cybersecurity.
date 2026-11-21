"""Tests for real model installation, offline loading, and end-to-end payment evidence storage."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.auth import analyst_passcode
from app.config import settings
from app.db import Database, set_db
from app.events import dispatch_once
from app.inference import Manifest, Runtime, set_runtime
from app.main import create_app
from app.soc.worker import run_once


@pytest.fixture(scope="module")
def sample_speech_pcm() -> bytes:
    """Generate or retrieve a speech sample with speech activity."""
    wav_path = Path("/tmp/sample_speech_16k.wav")
    if not wav_path.exists():
        # Synthesize via espeak-ng if missing
        cmd = 'espeak-ng -w /tmp/espeak_speech.wav "I authorize the transfer of five thousand rupees to Asha Rao" && ffmpeg -i /tmp/espeak_speech.wav -ar 16000 -ac 1 -c:a pcm_s16le /tmp/sample_speech_16k.wav -y'
        subprocess.run(cmd, shell=True, check=True)
    with wave.open(str(wav_path)) as w:
        return w.readframes(w.getnframes())


def test_manifest_reports_all_three_models_available():
    m = Manifest.load(settings.model_dir)
    assert m.get("asr").status == "available"
    assert m.get("spoof").status == "available"
    assert m.get("text_scam").status == "available"
    assert m.get("text_nli").status == "disabled"
    assert m.get("graph_gnn").status == "disabled"


def test_models_load_with_hf_hub_offline():
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    code = """
import os
from pathlib import Path
from app.config import settings
from app.inference import Manifest, Runtime

assert os.environ.get("HF_HUB_OFFLINE") == "1"
m = Manifest.load(settings.model_dir)
rt = Runtime(m)
for key in ("asr", "spoof", "text_scam"):
    obj = rt._load(key)
    assert obj is not None, f"Failed to load {key}"
print("ALL_LOADED_OFFLINE_OK")
"""
    res = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert "ALL_LOADED_OFFLINE_OK" in res.stdout


def test_real_inference_execution(sample_speech_pcm):
    m = Manifest.load(settings.model_dir)
    rt = Runtime(m)
    pcm = np.frombuffer(sample_speech_pcm, dtype="<i2")

    async def _run():
        # 1. ASR
        asr_obs = await rt.transcribe(pcm)
        assert asr_obs["status"] == "ok"
        assert asr_obs["source"] == "asr"
        assert len(asr_obs["text"]) > 0
        assert asr_obs["language"] == "en"

        # 2. Spoof
        spoof_obs = await rt.spoof(pcm)
        assert spoof_obs["status"] == "inconclusive" and spoof_obs["flagged"] is None
        assert spoof_obs["source"] == "spoof"
        assert isinstance(spoof_obs["score"], float)
        assert spoof_obs["prediction"] == ("fake" if spoof_obs["score"] >= 0.5 else "real")
        assert len(spoof_obs["points"]) > 0

        # 3. Text Scam (Classification)
        scam_text = "URGENT: Your account is suspended, send money immediately to verify."
        clean_text = "I am requesting one thousand rupees from Ravi for groceries."

        scam_res = await rt.classify_text("coercion_text", scam_text, "en")
        assert scam_res["source"] == "text_scam"
        assert scam_res["status"] == "flagged"
        assert scam_res["flagged"] is True
        assert scam_res["score"] > scam_res["threshold"] == 0.69

        clean_res = await rt.classify_text("coercion_text", clean_text, "en")
        assert clean_res["source"] == "text_scam"
        assert clean_res["status"] == "ok"
        assert clean_res["flagged"] is False
        assert clean_res["score"] < clean_res["threshold"] == 0.69
        unsupported = await rt.classify_text("typed_remark", "किराये के लिए पैसे चाहिए", None)
        assert unsupported["status"] == "unsupported_language" and unsupported["flagged"] is None

    asyncio.run(_run())


@pytest.mark.parametrize("provider", ["local", "wasitai"])
def test_payment_flow_stores_evidence_and_soc_displays_it(sample_speech_pcm, monkeypatch, provider):
    monkeypatch.setenv("TRINETRA_ANALYST_WORKSPACE_PASSWORD", "test-analyst-password")
    monkeypatch.setenv("TRINETRA_VOICE_PROVIDER", provider)
    monkeypatch.setenv("WASITAI_API_KEY", "test-key")

    def provider_failure(*args):
        raise subprocess.TimeoutExpired("curl", 50)

    monkeypatch.setattr("app.wasitai.detect", provider_failure)
    db_path = f"/tmp/trinetra-test-real-{uuid.uuid4().hex}.db"
    test_db = Database(f"sqlite:///{db_path}")
    test_db.migrate()
    set_db(test_db)

    m = Manifest.load(settings.model_dir)
    rt = Runtime(m)
    set_runtime(rt)

    try:
        app = create_app(start_background=False)
        with TestClient(app) as client:
            # 1. Customer session & onboarding
            s_tok = client.post("/api/v2/session").json()["token"]
            c_headers = {"Authorization": f"Bearer {s_tok}"}
            acct_id = client.post("/api/v2/accounts", json={"display_name": "Test Account"}, headers=c_headers).json()["id"]
            ben_id = client.post("/api/v2/beneficiaries", json={"display_name": "Merchant", "account_ref": "HDFC00088888"}, headers=c_headers).json()["id"]

            # 2. Voice capture
            cid = client.post("/api/v2/calls", json={"consent": True}, headers=c_headers).json()["id"]
            chunk = 32000
            for i in range(0, len(sample_speech_pcm), chunk):
                r = client.post(f"/api/v2/calls/{cid}/pcm", content=sample_speech_pcm[i:i + chunk], headers=c_headers)
                assert r.status_code == 200

            fin = client.post(f"/api/v2/calls/{cid}/finish", headers=c_headers)
            assert fin.status_code == 200
            call_data = fin.json()
            assert call_data["usable"] is True
            assert call_data["transcript_status"] == "ok"
            if provider == "local":
                assert call_data["voice_prediction"] in ("real", "fake")
            else:
                assert call_data["voice_prediction"] is None

            # 3. Submit payment
            pay_r = client.post("/api/v2/payments", json={
                "account_id": acct_id,
                "beneficiary_id": ben_id,
                "amount_minor": 20_000_00,  # ₹20,000 to trigger step-up
                "channel": "IMPS",
                "remark": "Urgent transfer",
                "call_id": cid,
            }, headers={**c_headers, "Idempotency-Key": uuid.uuid4().hex})
            assert pay_r.status_code == 201
            pid = pay_r.json()["payment_id"]

            # 4. Drain worker
            while run_once(test_db, "test"):
                pass
            dispatch_once(test_db)

            # 5. Analyst checks SOC case
            a_tok = client.post("/api/v2/soc/login", json={"name": "analyst.chief", "passcode": analyst_passcode()}).json()["token"]
            a_headers = {"Authorization": f"Bearer {a_tok}"}

            case_id = test_db.read(lambda t: t.scalar("SELECT id FROM cases WHERE payment_id = ?", (pid,)))
            case = client.get(f"/api/v2/soc/cases/{case_id}", headers=a_headers).json()

            # Confirm SOC case displays all signals and evidence
            signals = case["payment"]["signals"]
            expected_status = "inconclusive" if provider == "local" else "unavailable"
            assert signals["voice_authenticity"]["status"] == expected_status
            assert signals["speech_content"]["status"] == "ok"
            assert signals["typed_remark"]["status"] == "ok"

            ev_map = {e["kind"]: e for e in case["evidence"]}
            assert ev_map["voice_authenticity"]["payload"]["source"] == ("spoof" if provider == "local" else "wasitai")
            assert ev_map["voice_authenticity"]["status"] == expected_status
            if provider == "local":
                assert ev_map["voice_authenticity"]["model_id"] == "SpeechAntiSpoofingBenchmarks/AASIST-L"
                assert isinstance(ev_map["voice_authenticity"]["score"], float)
            login = client.post("/api/v2/analyst/login", json={"username": "admin", "password": "test-analyst-password"})
            workspace = client.get(f"/api/v2/analyst/cases/{case_id}",
                                   headers={"Authorization": f"Bearer {login.json()['token']}"})
            assert workspace.status_code == 200
            voice = next(e for e in workspace.json()["evidence"] if e["kind"] == "voice_authenticity")
            assert voice["prediction"] == call_data["voice_prediction"] and voice["review_only"] is True
            assert ev_map["speech_content"]["model_id"] == "bangta/Scam-detection"
            assert ev_map["transcript"]["model_id"] == "Systran/faster-whisper-base"
            assert ev_map["transcript"]["status"] == "ok"
            assert ev_map["typed_remark"]["model_id"] == "bangta/Scam-detection"
            assert "capture_quality" in ev_map
    finally:
        set_runtime(None)
        set_db(None)
