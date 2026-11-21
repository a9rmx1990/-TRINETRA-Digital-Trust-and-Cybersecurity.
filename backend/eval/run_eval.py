"""Evaluate frozen local checkpoints through the same adapters the gateway uses.

Data stays in this isolated directory and never enters the ledger or SOC analytics.

    # classification (voice authenticity or coercion text); labels.csv columns:
    #   id,split,label,language,path_or_text   (label: 1 = positive class, 0 = negative)
    python eval/run_eval.py classify --signal spoof --data eval/data/asvspoof_dev --split test
    python eval/run_eval.py classify --signal text_scam --data eval/data/coercion --split test

    # speech recognition; refs.csv columns: id,split,language,path,reference
    python eval/run_eval.py asr --data eval/data/kannada_asr --split test

Thresholds come from the manifest and must be frozen before the test split is opened.
Reports per-language counts, precision, recall, false-positive rate, abstention and
Wilson 95% intervals. Groups below --min-n are reported as insufficient.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import sys
from time import perf_counter
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = ref.lower().split(), hyp.lower().split()
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16 kHz mono 16-bit WAV")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def confusion_report(rows: list[dict], min_n: int) -> dict:
    groups: dict[str, dict] = defaultdict(lambda: {
        "tp": 0, "fp": 0, "tn": 0, "fn": 0, "abstain": 0, "abstain_positive": 0, "abstain_negative": 0,
    })
    for r in rows:
        keys = ["all", f"lang:{r['language']}"]
        if r.get("condition"):
            keys.append(f"condition:{r['condition']}")
        for g in keys:
            c = groups[g]
            if r["pred"] is None:
                c["abstain"] += 1
                c["abstain_positive" if r["label"] == 1 else "abstain_negative"] += 1
            elif r["label"] == 1:
                c["tp" if r["pred"] else "fn"] += 1
            else:
                c["fp" if r["pred"] else "tn"] += 1
    out = {}
    for g, c in sorted(groups.items()):
        pos, neg = c["tp"] + c["fn"], c["tn"] + c["fp"]
        total_pos, total_neg = pos + c["abstain_positive"], neg + c["abstain_negative"]
        out[g] = {**c, "positives": pos, "negatives": neg,
                  "total_positives": total_pos, "total_negatives": total_neg,
                  "synthetic_flag_rate": None if not total_pos else round(c["tp"] / total_pos, 4),
                  "genuine_flag_rate": None if not total_neg else round(c["fp"] / total_neg, 4),
                  "synthetic_miss_rate": None if not total_pos else round(c["fn"] / total_pos, 4),
                  "recall": None if not pos else round(c["tp"] / pos, 4), "recall_ci95": wilson(c["tp"], pos),
                  "false_positive_rate": None if not neg else round(c["fp"] / neg, 4), "fpr_ci95": wilson(c["fp"], neg),
                  "precision": None if not (c["tp"] + c["fp"]) else round(c["tp"] / (c["tp"] + c["fp"]), 4),
                  "abstention_rate": round(c["abstain"] / max(1, pos + neg + c["abstain"]), 4),
                  "sufficient": pos >= min_n and neg >= min_n}
    return out


async def classify(args, model_dir: Path | None = None) -> dict:
    from app.inference import Manifest, Runtime, measure_capture
    from app.config import settings
    directory = model_dir if model_dir is not None else settings.model_dir
    rt = Runtime(Manifest.load(directory), model_dir=directory)
    e = rt.manifest.get(args.signal)
    if not e or e.status != "available":
        return {"status": "not_run", "reason": f"{args.signal}: {e.status_reason if e else 'not in manifest'}"}
    rows = []
    latencies = []
    with open(Path(args.data) / "labels.csv") as f:
        for r in csv.DictReader(f):
            if r["split"] != args.split:
                continue
            if args.signal == "spoof":
                pcm = load_wav(Path(args.data) / r["path_or_text"])
                if measure_capture(pcm).usable:
                    start = perf_counter()
                    obs = await rt.spoof(pcm)
                    latencies.append((perf_counter() - start) * 1000)
                else:
                    obs = {"status": "inconclusive"}
            else:
                obs = await rt.classify_text("eval", r["path_or_text"], r["language"])
            pred = None if obs["status"] in ("unavailable", "inconclusive", "unsupported_language") else bool(obs["flagged"])
            rows.append({"id": r["id"], "label": int(r["label"]), "language": r["language"],
                         "condition": r.get("condition"), "pred": pred, "score": obs.get("score")})
    result = {"status": "run" if rows else "no_samples", "signal": args.signal, "model_id": e.model_id,
              "revision": e.revision, "threshold": None if e.diagnostic_only else e.threshold,
              "clear_below": None if e.diagnostic_only else e.clear_below,
              "positive_label": e.positive_label, "split": args.split, "n": len(rows),
              "report": confusion_report(rows, args.min_n)}
    if latencies:
        result["first_inference_ms"] = round(latencies[0])
        result["warm_p95_ms"] = round(float(np.percentile(latencies[1:], 95))) if len(latencies) > 1 else None
    if args.signal == "spoof" and not e.label_mapping_verified:
        result["unverified_cutoff_diagnostic"] = confusion_report([
            {**row, "pred": None if row["score"] is None else row["score"] >= e.threshold} for row in rows
        ], args.min_n)
    if getattr(args, "include_scores", False):
        result["scores"] = rows
    return result


async def compare(args) -> dict:
    return {"models": [await classify(args, path) for path in args.model_dir]}


async def asr(args) -> dict:
    from app.inference import Manifest, Runtime, coercion_rules
    from app.config import settings
    rt = Runtime(Manifest.load(settings.model_dir))
    e = rt.manifest.get("asr")
    if not e or e.status != "available":
        return {"status": "not_run", "reason": f"asr: {e.status_reason if e else 'not in manifest'}"}
    per = defaultdict(lambda: {"errors": 0, "words": 0, "n": 0, "critical_lost": 0, "rule_disagree": 0})
    with open(Path(args.data) / "refs.csv") as f:
        for r in csv.DictReader(f):
            if r["split"] != args.split:
                continue
            obs = await rt.transcribe(load_wav(Path(args.data) / r["path"]))
            hyp = obs.get("text") or ""
            e_, n_ = wer(r["reference"], hyp)
            ref_rules, hyp_rules = coercion_rules(r["reference"]), coercion_rules(hyp)
            for g in ("all", f"lang:{r['language']}"):
                p = per[g]
                p["errors"] += e_; p["words"] += n_; p["n"] += 1
                p["critical_lost"] += int(bool(ref_rules["hits"]) and not hyp_rules["hits"])
                p["rule_disagree"] += int(ref_rules["flagged"] != hyp_rules["flagged"])
    return {"status": "run", "model_id": e.model_id, "revision": e.revision, "split": args.split,
            "report": {g: {**v, "wer": None if not v["words"] else round(v["errors"] / v["words"], 4),
                           "sufficient": v["n"] >= args.min_n} for g, v in per.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify"); c.add_argument("--signal", required=True); c.add_argument("--data", required=True)
    c.add_argument("--split", default="test"); c.add_argument("--min-n", type=int, default=50)
    c.add_argument("--model-dir", type=lambda p: Path(p).resolve(), action="append",
                   help="Directory with manifest.json and local checkpoints. Repeat for a side-by-side comparison.")
    c.add_argument("--include-scores", action="store_true",
                   help="Include clip IDs, labels and model scores for offline threshold comparisons.")
    a = sub.add_parser("asr"); a.add_argument("--data", required=True); a.add_argument("--split", default="test")
    a.add_argument("--min-n", type=int, default=50)
    args = ap.parse_args()
    if args.cmd == "asr":
        res = asyncio.run(asr(args))
    elif args.model_dir:
        res = asyncio.run(compare(args))
    else:
        res = asyncio.run(classify(args))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
