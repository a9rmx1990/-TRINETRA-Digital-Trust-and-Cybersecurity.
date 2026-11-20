"""Fit a logistic stacker and calibrate it on a separate, reviewed split."""

import argparse
import json
from pathlib import Path

import numpy as np

from app.live.models import FUSION_FEATURES, fusion_features


def load(path):
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    y = np.asarray([row["label"] for row in records], dtype=float)
    if set(y) != {0, 1}:
        raise ValueError(f"{path} must contain both labels")
    scores = [tuple(row[name] for name in ("voice", "text", "graph")) for row in records]
    if any(score is not None and not 0 <= score <= 100 for row in scores for score in row):
        raise ValueError("Scores must be null or in [0, 100]")
    if len({row["id"] for row in records}) != len(records):
        raise ValueError(f"{path} contains duplicate IDs")
    return np.asarray([fusion_features(*row) for row in scores]), y, {row["id"] for row in records}


def sigmoid(value):
    return 1 / (1 + np.exp(-np.clip(value, -60, 60)))


def fit(x, y, iterations=2500):
    design = np.column_stack((np.ones(len(x)), x))
    weights = np.zeros(design.shape[1])
    for _ in range(iterations):
        gradient = design.T @ (sigmoid(design @ weights) - y) / len(y)
        weights -= 0.1 * gradient
    return weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("train", type=Path)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("test", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-versions", nargs=3, required=True, metavar=("VOICE", "TEXT", "GRAPH"))
    args = parser.parse_args()
    x, y, train_ids = load(args.train)
    validation, labels, calibration_ids = load(args.calibration)
    test, test_labels, test_ids = load(args.test)
    if train_ids & calibration_ids or train_ids & test_ids or calibration_ids & test_ids:
        raise ValueError("Training, calibration and test IDs must be disjoint")
    bias, *weights = fit(x, y)
    offset, scale = fit((validation @ weights + bias)[:, None], labels)
    probabilities = sigmoid(test @ (np.array(weights) * scale) + bias * scale + offset)
    report = {"test_rows": len(test), "test_brier": float(np.mean((probabilities - test_labels) ** 2)),
              "test_log_loss": float(-np.mean(test_labels * np.log(np.clip(probabilities, 1e-12, 1)) +
                                             (1-test_labels) * np.log(np.clip(1-probabilities, 1e-12, 1))))}
    artifact = {"features": FUSION_FEATURES, "intercept": float(bias * scale + offset),
                "weights": (np.array(weights) * scale).tolist(), "metrics": report,
                "model_versions": [None if v == "-" else v for v in args.model_versions]}
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
