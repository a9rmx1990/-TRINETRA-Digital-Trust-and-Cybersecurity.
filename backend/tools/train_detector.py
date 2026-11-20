"""Fine-tune a local wav2vec2/WavLM or XLM-R checkpoint on labeled JSONL."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from transformers import (AutoFeatureExtractor, AutoModelForAudioClassification,
                          AutoModelForSequenceClassification, AutoTokenizer)

from app.live.models import SAMPLE_RATE
from app.engines.audio_engine import AudioForensicsEngine


def read(path, modality, label_ids):
    rows = {}
    decoder = AudioForensicsEngine()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in rows:
            raise ValueError("Duplicate example ID")
        labels = row["labels"]
        if not labels or any(label not in label_ids for label in labels):
            raise ValueError("Unknown or empty labels")
        if modality == "audio":
            if len(labels) != 1:
                raise ValueError("Voice classification requires one label")
            source = path.parent / row["audio"]
            if source.suffix.lower() != ".wav" or source.stat().st_size > 8_000_000:
                raise ValueError("Provide a bounded WAV for each training example")
            audio = decoder.parse_audio(source.read_bytes())
            if not 1 <= len(audio) / SAMPLE_RATE <= 3:
                raise ValueError("Provide one to three seconds of speech per example")
            rows[row["id"]] = (audio, label_ids[labels[0]])
        else:
            rows[row["id"]] = (row["text"], [float(label in labels) for label in label_ids])
    if not rows:
        raise ValueError("Dataset split is empty")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modality", choices=("audio", "text"))
    parser.add_argument("base_model", type=Path)
    parser.add_argument("train", type=Path)
    parser.add_argument("test", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    labels = dict(zip(args.labels, range(len(args.labels))))
    if len(labels) != len(args.labels) or len(labels) < 2 or min(args.epochs, args.batch_size) < 1:
        parser.error("Use unique labels, positive epochs and a positive batch size")
    if args.modality == "audio" and len(labels) != 2:
        parser.error("Specify two audio labels in checkpoint order")
    train, test = read(args.train, args.modality, labels), read(args.test, args.modality, labels)
    if train.keys() & test.keys():
        raise ValueError("Training and test IDs overlap")
    torch.manual_seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    audio = args.modality == "audio"
    processor_class = AutoFeatureExtractor if audio else AutoTokenizer
    model_class = AutoModelForAudioClassification if audio else AutoModelForSequenceClassification
    processor = processor_class.from_pretrained(args.base_model, local_files_only=True)
    model = model_class.from_pretrained(
        args.base_model, local_files_only=True, num_labels=len(labels),
        label2id=labels, id2label={i: label for label, i in labels.items()},
        ignore_mismatched_sizes=True,
        problem_type="single_label_classification" if audio else "multi_label_classification",
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)

    def batch(examples):
        x, y = zip(*examples)
        options = {"sampling_rate": SAMPLE_RATE} if audio else {"truncation": True, "max_length": 256}
        tokens = processor(list(x), padding=True, return_tensors="pt", **options).to(device)
        return tokens, torch.tensor(y, dtype=torch.long if audio else torch.float32, device=device)

    examples = list(train.values())
    for _ in range(args.epochs):
        model.train()
        indexes = torch.randperm(len(examples)).tolist()
        for start in range(0, len(indexes), args.batch_size):
            tokens, y = batch([examples[i] for i in indexes[start:start + args.batch_size]])
            optimizer.zero_grad()
            model(**tokens, labels=y).loss.backward()
            optimizer.step()

    model.eval()
    counts = np.zeros((len(labels), 3), dtype=int)
    examples = list(test.values())
    with torch.inference_mode():
        for start in range(0, len(examples), args.batch_size):
            tokens, y = batch(examples[start:start + args.batch_size])
            logits = model(**tokens).logits
            prediction = (torch.nn.functional.one_hot(logits.argmax(-1), len(labels)).bool()
                          if audio else logits.sigmoid() >= 0.5)
            actual = torch.nn.functional.one_hot(y, len(labels)).bool() if audio else y.bool()
            counts += torch.stack(((prediction & actual).sum(0), (prediction & ~actual).sum(0),
                                   (~prediction & actual).sum(0)), dim=1).cpu().numpy()
    args.output.mkdir(parents=True, exist_ok=True)
    processor.save_pretrained(args.output)
    model.save_pretrained(args.output)
    report = {label: {"tp": int(counts[i, 0]), "fp": int(counts[i, 1]), "fn": int(counts[i, 2])}
              for label, i in labels.items()}
    (args.output / "held_out_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
