"""Upload one audio clip to WasItAIGenerated. A success costs 1,000 credits."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

URL = "https://www.wasitaigenerated.com/api/v1/detect/audio"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    audio = parser.parse_args().audio
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    key = os.getenv("WASITAI_API_KEY", "").strip()
    if not key:
        parser.exit(1, "Set WASITAI_API_KEY in the project .env.\n")
    try:
        extension = audio.suffix.lower()
        if extension not in {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".webm"}:
            parser.exit(1, "Choose a supported audio file.\n")
        if not 0 < audio.stat().st_size <= 4_000_000:
            parser.exit(1, "Choose a nonempty audio file up to 4 MB.\n")
        # Pass the authorization header over stdin so it stays out of process arguments.
        header = json.dumps(f"Authorization: Bearer {key}")
        result = subprocess.run(
            ["curl", "--silent", "--show-error", "--connect-timeout", "15", "--max-time", "65",
             "--config", "-", "--form", f"file=@{json.dumps(str(audio.resolve()), ensure_ascii=False)};filename=clip{extension}",
             "--write-out", "\n%{http_code}", URL],
            input=f"header = {header}\n", text=True, capture_output=True,
        )
        if result.returncode:
            parser.exit(1, f"Connection to WasItAIGenerated failed (curl exit {result.returncode}).\n")
        body, _, status = result.stdout.rpartition("\n")
        if status != "200":
            parser.exit(1, f"WasItAIGenerated returned HTTP {status}.\n")
        data = json.loads(body)
        verdict = data.get("verdict")
        if verdict not in ("ai", "human", "uncertain"):
            parser.exit(1, "The provider did not return a recognized verdict.\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Audio check failed ({type(exc).__name__}).\n")
    print(json.dumps({key: data.get(key) for key in ("verdict", "score", "warnings", "creditsCharged")}, indent=2))


if __name__ == "__main__":
    main()
