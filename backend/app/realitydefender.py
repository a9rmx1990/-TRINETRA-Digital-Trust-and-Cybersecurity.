"""Reality Defender analysis of a completed voice clip."""
import asyncio
import io
import wave
from urllib.parse import quote

import httpx
import numpy as np

API = "https://api.prd.realitydefender.xyz"
PREDICTIONS = {"AUTHENTIC": "real", "FAKE": "fake", "SUSPICIOUS": "uncertain"}


async def detect(audio: np.ndarray, key: str) -> dict:
    wav = io.BytesIO()
    with wave.open(wav, "wb") as writer:
        writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
        writer.writeframes(audio.astype("<i2", copy=False).tobytes())

    headers = {"X-API-KEY": key}
    async with asyncio.timeout(55), httpx.AsyncClient(timeout=12) as client:
        response = await client.post(f"{API}/api/files/aws-presigned", headers=headers,
                                     json={"fileName": "voice-clip.wav"})
        response.raise_for_status()
        target = response.json()
        signed_url = httpx.URL(target["response"]["signedUrl"])
        if signed_url.scheme != "https" or not signed_url.host:
            raise ValueError("Invalid Reality Defender upload URL")
        request_id = quote(target["requestId"], safe="")
        # The signed upload URL authorizes the PUT on its own.
        upload = await client.put(signed_url, content=wav.getvalue())
        upload.raise_for_status()

        while True:
            result = await client.get(f"{API}/api/media/users/{request_id}", headers=headers)
            result.raise_for_status()
            data = result.json()
            verdict = data["overallStatus"]
            if verdict not in ("ANALYZING", "DOWNLOADING"):
                break
            await asyncio.sleep(2)

    if verdict not in PREDICTIONS:
        raise ValueError("Reality Defender could not evaluate the audio")
    score = ((data.get("resultsSummary") or {}).get("metadata") or {}).get("finalScore")
    return {
        "signal": "voice_authenticity", "status": "inconclusive", "review_only": True,
        "source": "realitydefender", "model_id": "Reality Defender audio ensemble", "revision": None,
        "score_scale": "Provider manipulation score (0–100)",
        "score": score if type(score) in (int, float) and 0 <= score <= 100 else None,
        "flagged": None, "points": [], "prediction": PREDICTIONS[verdict],
        "reason": "External voice prediction for analyst review",
    }
