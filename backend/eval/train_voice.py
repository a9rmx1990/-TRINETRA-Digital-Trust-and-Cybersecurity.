"""Fit a local Wav2Vec2 spoof head and export a TRINETRA evaluation manifest."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

from run_eval import confusion_report, load_wav
from app.inference import measure_capture

RATE = 16_000
WINDOW = RATE * 2


def read_split(data: Path, split: str) -> list[dict]:
    with (data / "labels.csv").open(newline="") as file:
        return [r | {"label": int(r["label"])} for r in csv.DictReader(file) if r["split"] == split]


@torch.inference_mode()
def embed(rows, data, feature_extractor, model, device):
    features, labels, clip_indices = [], [], []
    for i, row in enumerate(rows):
        clip = load_wav(data / row["path_or_text"])
        if not measure_capture(clip).usable:
            continue
        windows = [clip[j:j + WINDOW] for j in range(0, max(1, len(clip) - WINDOW // 2), WINDOW)]
        windows = [w.astype(np.float32) / 32768 for w in windows if len(w) >= WINDOW // 2]
        for j in range(0, len(windows), 8):
            batch = windows[j:j + 8]
            inputs = feature_extractor(batch, sampling_rate=RATE, padding="max_length",
                                       max_length=WINDOW, truncation=True, return_tensors="pt")
            inp = inputs["input_values"].to(device)
            hidden = model.wav2vec2(inp).last_hidden_state
            features.append(model.projector(hidden).mean(dim=1).cpu())
            labels.extend([row["label"]] * len(batch))
            clip_indices.extend([i] * len(batch))
    if not features or set(labels) != {0, 1}:
        raise SystemExit("The split needs usable clips from both classes.")
    return torch.cat(features), torch.tensor(labels), clip_indices


def select_cutoffs(scored: list[dict], limit: float = 0.05) -> tuple[float, float]:
    genuine = np.array([r["score"] for r in scored if r["label"] == 0])
    spoof = np.array([r["score"] for r in scored if r["label"] == 1])
    if min(len(genuine), len(spoof)) < 10:
        raise SystemExit("Need at least ten scored development clips per class.")
    values = set(genuine) | set(spoof)
    candidates = sorted({0.0, 1.0, *values, *(round(x + .0001, 4) for x in values if x < 1)})
    low = [x for x in candidates if (spoof < x).mean() <= limit]
    high = [x for x in candidates if (genuine >= x).mean() <= limit]
    pairs = [(a, b) for a in low for b in high if a < b]
    if not pairs:
        raise SystemExit("No cutoff pair meets the development error limits.")
    return max(pairs, key=lambda p: ((genuine < p[0]).mean() + (spoof >= p[1]).mean(), p[1] - p[0]))


def train(data: Path, base: Path, output: Path, device: str) -> None:
    torch.manual_seed(42)
    torch.set_num_threads(2)
    training, dev = (read_split(data, name) for name in ("train", "dev"))
    train_speakers = {row.get("speaker") for row in training} - {None, ""}
    dev_speakers = {row.get("speaker") for row in dev} - {None, ""}
    if train_speakers & dev_speakers:
        raise SystemExit("Training and development speakers must be disjoint.")
    fx = AutoFeatureExtractor.from_pretrained(base, local_files_only=True)
    model = AutoModelForAudioClassification.from_pretrained(base, local_files_only=True).eval().to(device)
    if model.config.use_weighted_layer_sum or fx.return_attention_mask:
        raise SystemExit("Use a Wav2Vec2 checkpoint with unweighted pooling and no attention mask.")
    print(f"Extracting training features on {device}.", flush=True)
    x, y, train_indices = embed(training, data, fx, model, device)
    print(f"Extracting development features ({len(dev)} clips).", flush=True)
    vx, _, indices = embed(dev, data, fx, model, device)
    head = torch.nn.Linear(x.shape[1], 2)
    loss_fn = torch.nn.CrossEntropyLoss(weight=len(y) / (2 * torch.bincount(y)))
    optimizer = torch.optim.AdamW(head.parameters(), lr=.003)
    x, y, vx = x.clone(), y.clone(), vx.clone()
    for _ in range(160):
        optimizer.zero_grad()
        loss_fn(head(x), y).backward()
        optimizer.step()
    score_by_clip = {}
    with torch.no_grad():
        for i, score in zip(indices, torch.softmax(head(vx), dim=1)[:, 1].tolist()):
            score_by_clip[i] = max(score_by_clip.get(i, 0.0), round(score, 4))
    scored = [row | {"score": score_by_clip[i]} for i, row in enumerate(dev) if i in score_by_clip]
    low, high = select_cutoffs(scored)
    report = []
    for i, row in enumerate(dev):
        score = score_by_clip.get(i)
        pred = None if score is None or low <= score < high else score >= high
        report.append(row | {"pred": pred})
    model.classifier.load_state_dict(head.state_dict())
    model.config.id2label = {0: "genuine", 1: "spoof"}
    model.config.label2id = {"genuine": 0, "spoof": 1}
    output.mkdir(parents=True, exist_ok=False)
    model.cpu().save_pretrained(output, safe_serialization=True)
    fx.save_pretrained(output)
    with (output / "model.safetensors").open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    manifest = {"models": {"spoof": {
        "signal": "voice_authenticity", "kind": "audio_classification", "enabled": True,
        "path": ".", "model_id": "local/asvspoof-wav2vec2-pilot", "revision": digest[:12],
        "positive_label": "spoof", "window_s": WINDOW / RATE, "clear_below": low, "threshold": high,
        "checksum_file": "model.safetensors", "sha256": digest, "enforce": False,
    }}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    results = {"train_clips": len(set(train_indices)), "dev_scored": len(scored),
               "clear_below": low, "flag_at": high, "development": confusion_report(report, min_n=10)}
    (output / "training-report.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["development"]["all"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    train(args.data, args.base, args.output, args.device)
