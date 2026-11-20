"""Train a directed message-passing classifier and export TorchScript."""

import argparse
import json
from pathlib import Path

import torch
from torch import nn


class DirectedGraphLayer(nn.Module):
    def __init__(self, inputs: int, outputs: int):
        super().__init__()
        self.self_projection = nn.Linear(inputs, outputs)
        self.incoming = nn.Linear(inputs, outputs, bias=False)
        self.outgoing = nn.Linear(inputs, outputs, bias=False)

    def forward(self, x: torch.Tensor, edges: torch.Tensor) -> torch.Tensor:
        source, target = edges[0], edges[1]
        count = torch.ones((source.numel(), 1), dtype=x.dtype, device=x.device)
        zeros = torch.zeros_like(x[:, :1])
        inbound = torch.zeros_like(x).index_add(0, target, x[source])
        outbound = torch.zeros_like(x).index_add(0, source, x[target])
        inbound = inbound / zeros.index_add(0, target, count).clamp_min(1)
        outbound = outbound / zeros.index_add(0, source, count).clamp_min(1)
        return (self.self_projection(x) + self.incoming(inbound) + self.outgoing(outbound)).relu()


class MuleGNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.first = DirectedGraphLayer(4, 32)
        self.second = DirectedGraphLayer(32, 32)
        self.result = nn.Linear(32, 1)

    def forward(self, features: torch.Tensor, edges: torch.Tensor) -> torch.Tensor:
        embedded = self.first(features, edges)
        return self.result((embedded + self.second(embedded, edges))[0])


def records(path):
    rows = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        x = torch.tensor(row["features"], dtype=torch.float32)
        edges = torch.tensor(row["edges"], dtype=torch.long).reshape(-1, 2).T
        if x.ndim != 2 or x.shape[1] != 4 or not len(x) or not torch.isfinite(x).all():
            raise ValueError("Expected one or more finite four-feature rows")
        if edges.numel() and (edges.min() < 0 or edges.max() >= len(x)):
            raise ValueError("Invalid graph edge index")
        if row["id"] in rows or row["label"] not in (0, 1):
            raise ValueError("Duplicate ID or invalid label")
        rows[row["id"]] = (x, edges, torch.tensor([row["label"]], dtype=torch.float32))
    if {row[2].item() for row in rows.values()} != {0, 1}:
        raise ValueError("Both classes are required in each split")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("train", type=Path)
    parser.add_argument("test", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error("Expected at least one epoch")
    torch.manual_seed(42)
    train, test = records(args.train), records(args.test)
    if train.keys() & test.keys():
        raise ValueError("Training and test IDs must be disjoint")
    model = MuleGNN()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
    loss = nn.BCEWithLogitsLoss()
    examples = list(train.values())
    for _ in range(args.epochs):
        for index in torch.randperm(len(examples)).tolist():
            x, edges, y = examples[index]
            optimizer.zero_grad()
            loss(model(x, edges), y).backward()
            optimizer.step()
    model.eval()
    with torch.inference_mode():
        scores = torch.cat([model(x, edges).sigmoid() for x, edges, _ in test.values()])
        labels = torch.cat([y for _, _, y in test.values()])
    order = torch.argsort(scores, descending=True)
    ranked = labels[order]
    distinct = torch.where(torch.cat((scores[order][:-1] != scores[order][1:], torch.tensor([True]))))[0]
    hits = ranked.cumsum(0)[distinct]
    increments = torch.diff(hits, prepend=torch.zeros(1))
    average_precision = ((hits / (distinct + 1)) * increments).sum() / ranked.sum()
    predicted = scores >= 0.5
    tp = int((predicted & labels.bool()).sum())
    fp = int((predicted & ~labels.bool()).sum())
    positives = int(labels.sum())
    torch.jit.script(model).save(str(args.output))
    print(json.dumps({"train_rows": len(train), "test_rows": len(test), "test_positives": positives,
                      "test_brier": float((scores - labels).square().mean()),
                      "test_average_precision": float(average_precision),
                      "test_false_positives_at_0_5": fp, "test_true_positives_at_0_5": tp}))


if __name__ == "__main__":
    main()
