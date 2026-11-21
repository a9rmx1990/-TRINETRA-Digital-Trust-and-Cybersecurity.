"""Backend adapter for WasItAIGenerated's completed-clip detection endpoint."""
import io
import json
import os
import subprocess
import wave

import numpy as np

URL = "https://www.wasitaigenerated.com/api/v1/detect/audio"
PREDICTIONS = {"ai": "fake", "human": "real", "uncertain": "uncertain"}


def detect(audio: np.ndarray, key: str) -> dict:
    wav = io.BytesIO()
    with wave.open(wav, "wb") as writer:
        writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
        writer.writeframes(audio.astype("<i2", copy=False).tobytes())

    # Curl reads the WAV from stdin. The API key stays out of command arguments.
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--fail", "--write-out", "\n%{http_code}", "--connect-timeout", "12",
         "--max-time", "50", "--variable", "%WASITAI_API_KEY",
         "--expand-header", "Authorization: Bearer {{WASITAI_API_KEY}}",
         "--form", "file=@-;filename=clip.wav;type=audio/wav", URL],
        input=wav.getvalue(), capture_output=True, timeout=52,
        env={**os.environ, "WASITAI_API_KEY": key},
    )
    body, _, status = result.stdout.rpartition(b"\n")
    if status == b"402":
        raise ValueError("WasItAIGenerated requires 1,000 available credits for an audio check")
    if result.returncode:
        code = status.decode() if status.isdigit() and status != b"000" else "unavailable"
        raise ValueError(f"WasItAIGenerated request failed (HTTP {code}, curl exit {result.returncode})")
    data = json.loads(body)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if not isinstance(verdict, str) or verdict not in PREDICTIONS:
        raise ValueError("WasItAIGenerated did not return a recognized verdict")
    score = data.get("score")
    return {
        "signal": "voice_authenticity", "status": "inconclusive", "review_only": True,
        "source": "wasitai", "model_id": "WasItAIGenerated/tropa-voice", "revision": None,
        "score_scale": "Provider AI score (0–100)", "score": score if type(score) in (int, float) and 0 <= score <= 100 else None,
        "flagged": None, "points": [], "prediction": PREDICTIONS[verdict],
        "reason": "External voice prediction for analyst review",
    }
