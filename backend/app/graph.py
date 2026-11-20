"""Deterministic recipient-graph evidence from actual settled transfers.

The graph is bounded in time window, depth and node count. The proposed transfer is
kept separate from settled history. No learned graph score is used; the adapter slot
stays disabled in the active manifest until a published, evaluated checkpoint exists.
"""
from __future__ import annotations

from typing import Any

import networkx as nx

from . import clock
from .db import Tx

WINDOW_DAYS = 90
MAX_DEPTH = 2
MAX_NODES = 200
FAN_IN_WINDOW_MS = 7 * clock.DAY
FAN_IN_THRESHOLD = 3


def watermark(t: Tx) -> dict:
    row = t.one("SELECT COUNT(*) AS n, COALESCE(MAX(created_ms), 0) AS last_ms FROM settlements")
    return {"settlements": int(row["n"]), "last_ms": int(row["last_ms"])}


def _endpoints(account_id: str, counterparty_id: str, direction: str) -> tuple[str, str]:
    account, contact = f"acct:{account_id}", f"cp:{counterparty_id}"
    return (contact, account) if direction == "incoming" else (account, contact)


def build(t: Tx, *, owner_id: str, account_id: str, counterparty_id: str, at_ms: int,
          direction: str = "outgoing", proposed: dict | None = None) -> dict[str, Any]:
    since = at_ms - WINDOW_DAYS * clock.DAY
    g = nx.DiGraph()
    sender, recipient = _endpoints(account_id, counterparty_id, direction)
    frontier = {sender, recipient}
    seen: set[str] = set()
    truncated = False
    edges: dict[tuple[str, str], list[dict]] = {}
    seen_settlements: set[str] = set()
    for depth in range(MAX_DEPTH):
        nxt: set[str] = set()
        for node in frontier - seen:
            seen.add(node)
            kind, nid = node.split(":", 1)
            column = "counterparty_id" if kind == "cp" else "account_id"
            rows = t.all("SELECT s.id, s.payment_id, s.account_id, s.counterparty_id, s.amount_minor, s.created_ms,"
                         " s.owner_id, p.direction FROM settlements s JOIN payments p ON p.id = s.payment_id"
                         f" WHERE s.{column} = ? AND s.created_ms BETWEEN ? AND ?"
                         " ORDER BY s.created_ms DESC LIMIT 100", (nid, since, at_ms))
            for r in rows:
                if r["id"] in seen_settlements:
                    continue
                seen_settlements.add(r["id"])
                a, b = _endpoints(r["account_id"], r["counterparty_id"], r["direction"])
                edges.setdefault((a, b), []).append({"payment_id": r["payment_id"], "settlement_id": r["id"],
                                                     "amount_minor": r["amount_minor"], "created_ms": r["created_ms"],
                                                     "owner_id": r["owner_id"]})
                for n in (a, b):
                    if n not in g:
                        if g.number_of_nodes() >= MAX_NODES:
                            truncated = True
                            continue
                        g.add_node(n)
                    nxt.add(n)
                if a in g and b in g:
                    g.add_edge(a, b)
        frontier = nxt
        if depth == MAX_DEPTH - 1 and (frontier - seen):
            truncated = True

    inbound = edges_into(edges, recipient)
    recent_since = at_ms - FAN_IN_WINDOW_MS
    if direction == "incoming":
        other_senders = {a for (a, b), v in edges.items() if b == recipient and a != sender
                         and any(e["created_ms"] >= recent_since for e in v)}
        prior = edges.get((sender, recipient), [])
    else:
        other_senders = {e["owner_id"] for e in inbound
                         if e["owner_id"] != owner_id and e["created_ms"] >= recent_since}
        prior = [e for e in inbound if e["owner_id"] == owner_id]
    fan_in = len(other_senders) >= FAN_IN_THRESHOLD
    reasons = []
    if fan_in:
        reasons.append(f"recipient received settled transfers from {len(other_senders)} other senders in 7 days")
    if not prior:
        reasons.append("no prior settled transfer in this direction between the parties")

    labels = _labels(t, g.nodes)
    nodes = [{"id": n, "kind": n.split(":")[0], "label": labels.get(n, n.split(":")[1][-6:]),
              "is_sender": n == sender, "is_recipient": n == recipient} for n in g.nodes]
    for n in (sender, recipient):
        if n not in g:
            nodes.append({"id": n, "kind": n.split(":")[0], "label": labels.get(n) or _label_one(t, n),
                          "is_sender": n == sender, "is_recipient": n == recipient})
    edge_list = [{"source": a, "target": b, "transfers": sorted(v, key=lambda e: e["created_ms"]),
                  "proposed": False} for (a, b), v in edges.items()]
    if proposed:
        edge_list.append({"source": sender, "target": recipient, "transfers": [proposed], "proposed": True})
    features = {"recent_distinct_other_senders": len(other_senders),
                "prior_settled_between_parties": len(prior), "inbound_settled_total": len(inbound)}
    if direction == "outgoing":
        features["prior_settled_from_owner"] = len(prior)
    return {
        "method": "networkx-bounded-bfs",
        "window_days": WINDOW_DAYS, "max_depth": MAX_DEPTH, "max_nodes": MAX_NODES, "truncated": truncated,
        "as_of_ms": at_ms, "nodes": nodes, "edges": edge_list,
        "features": features,
        "fan_in": fan_in, "new_relationship": not prior, "reasons": reasons,
    }


def edges_into(edges: dict, node: str) -> list[dict]:
    out = []
    for (a, b), v in edges.items():
        if b == node:
            out.extend(v)
    return out


def _labels(t: Tx, nodes) -> dict[str, str]:
    return {n: _label_one(t, n) for n in nodes}


def _label_one(t: Tx, n: str) -> str:
    kind, nid = n.split(":", 1)
    if kind == "acct":
        r = t.one("SELECT account_ref FROM accounts WHERE id = ?", (nid,))
    else:
        r = t.one("SELECT account_ref FROM counterparties WHERE id = ?", (nid,))
    ref = r["account_ref"] if r else nid
    return "•••• " + ref[-4:]


def signal_from_graph(gr: dict) -> dict:
    return {"signal": "recipient_graph", "status": "flagged" if gr["fan_in"] else "ok",
            "review_only": False, "source": "graph", "model_id": "deterministic:networkx",
            "revision": f"bfs-d{MAX_DEPTH}-w{WINDOW_DAYS}", "score_scale": "distinct other senders in 7 days (count)",
            "score": gr["features"]["recent_distinct_other_senders"], "flagged": gr["fan_in"],
            "truncated": gr["truncated"], "new_relationship": gr["new_relationship"], "reasons": gr["reasons"],
            "points": [], "learned_graph_model": "disabled in active manifest"}
