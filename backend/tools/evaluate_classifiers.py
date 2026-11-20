"""Evaluate local text, audio spoof and speech-transcript classifiers."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from app.live.models import SAMPLE_RATE, models

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/classification.jsonl"


def examples(mode, cases, root):
    for number, row in enumerate(cases, 1):
        if mode == "text":
            yield str(number), row, None
        elif isinstance(row.get("audio"), str):
            yield str(number), row, root / row["audio"]
        elif row.get("audio") is True:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "speech.wav"
                for engine in ("espeak-ng", "flite"):
                    args = ([engine, "-v", "en-us", "-w", path, row["text"]] if engine == "espeak-ng"
                            else [engine, "-voice", "slt", "-t", row["text"], "-o", path])
                    subprocess.run(args, check=True)
                    yield f"{number}/{engine}", row | {"voice_label": "fake"}, path


def decode(path, full_clip):
    duration = [] if full_clip else ["-af", "apad", "-t", "2"]
    pcm = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", str(path), *duration,
                                   "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "s16le", "-"])
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768


def score(signal):
    if signal.get("status") != "ready":
        sys.exit(f"Classifier {signal.get('status')}. Check the local model manifest and input.")
    return signal["score"]


def text_label(text, language):
    if not text.strip():
        return "inconclusive"
    return "risk" if score(models.text_score(text, language)) >= 69 else "benign"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["text", "audio", "transcript"])
    parser.add_argument("--cases", type=Path, default=FIXTURE)
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    counts = Counter()
    for name, row, path in examples(args.mode, cases, args.cases.parent):
        if args.mode == "audio":
            pcm = decode(path, False)
            configured = models.manifest["spoof"]["positive_index"]
            expected = row["voice_label"]
            if expected not in {"real", "fake"}:
                parser.error("Expected real or fake voice_label")
            for seconds in (1, 2):
                probability = score(models.spoof_score(pcm[:seconds * SAMPLE_RATE]))
                for index in (0, 1):
                    fake_score = probability if index == configured else 100 - probability
                    label = "fake" if fake_score >= 50 else "real"
                    counts[(f"{seconds}s class {index} as fake", expected, label)] += 1
        else:
            expected = row["expected"]
            reference = text_label(row["text"], row["language"])
            counts[(f"{row['language']} reference", expected, reference)] += 1
            if args.mode == "transcript":
                asr = models.transcript(decode(path, True))
                if asr["status"] == "unavailable" or asr["status"] == "missing":
                    sys.exit(f"Transcription model {asr['status']}.")
                predicted = text_label(asr.get("text", ""), asr.get("language"))
                counts[(f"{row['language']} Whisper", expected, predicted)] += 1
                print(f"{name}: expected {expected}, reference {reference}, Whisper {predicted}", flush=True)
    if not counts:
        parser.error("No matching examples")
    for (variant, expected, actual), count in sorted(counts.items()):
        print(f"{variant}: expected {expected}, predicted {actual}: {count}")


if __name__ == "__main__":
    main()
