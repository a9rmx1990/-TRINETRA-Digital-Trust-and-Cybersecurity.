"""Check one audio file with Resemble Detect from the project root.

Run: .venv/bin/python backend/tools/resemble_detect.py /path/to/audio.wav
The specified file is uploaded to Resemble and may consume detection credits.
"""
import argparse
import json
import os
import time
from pathlib import Path
from uuid import UUID

import httpx
from dotenv import load_dotenv

DETECT_URL = "https://app.resemble.ai/api/v2/detect"
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".aac", ".flac", ".amr", ".3gp", ".3gpp"}


def detection_item(response: httpx.Response) -> dict:
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success") or not isinstance(payload.get("item"), dict):
        raise ValueError("Resemble returned an invalid detection response.")
    return payload["item"]


def detect_audio(client: httpx.Client, audio: Path) -> dict:
    if audio.suffix.lower() not in AUDIO_EXTENSIONS or not 0 < audio.stat().st_size <= 150_000_000:
        raise ValueError("Choose a supported, nonempty audio file of at most 150 MB.")
    with audio.open("rb") as source:
        item = detection_item(client.post(DETECT_URL, files={"file": ("clip" + audio.suffix, source)}))
    job_id = UUID(item["uuid"])
    deadline = time.monotonic() + 120
    while item.get("status") in ("pending", "queued", "processing"):
        if time.monotonic() >= deadline:
            raise ValueError(f"Detection is still pending. Job UUID: {job_id}")
        time.sleep(3)
        item = detection_item(client.get(f"{DETECT_URL}/{job_id}"))
    if item.get("status") != "completed":
        raise ValueError(f"Resemble did not complete detection. Job UUID: {job_id}")
    metrics = item.get("metrics") or {}
    if not metrics.get("label"):
        raise ValueError(f"Resemble completed the job without an audio verdict. Job UUID: {job_id}")
    return {"uuid": str(job_id), "label": metrics["label"], "score": metrics.get("aggregated_score"),
            "consistency": metrics.get("consistency")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    args = parser.parse_args()
    load_dotenv(ROOT_ENV)
    key = os.getenv("RESEMBLE_API_KEY", "").strip()
    if not key:
        parser.exit(1, "Set RESEMBLE_API_KEY in the root .env file.\n")
    try:
        with httpx.Client(timeout=20, headers={"Authorization": f"Bearer {key}"}) as client:
            result = detect_audio(client, args.audio)
    except httpx.HTTPStatusError as exc:
        parser.exit(1, f"Resemble Detect returned HTTP {exc.response.status_code}.\n")
    except httpx.RequestError as exc:
        parser.exit(1, f"Resemble Detect request failed ({type(exc).__name__}).\n")
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
