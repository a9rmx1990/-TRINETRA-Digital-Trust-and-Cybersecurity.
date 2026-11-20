"""Bounded event-time evidence from a directed multigraph of settled transfers."""

from collections import deque
import math
import networkx as nx


def analyze(rows, sender, recipient, age, now):
    graph = nx.MultiDiGraph()
    graph.add_nodes_from([sender, recipient])
    for row in rows:
        graph.add_edge(row["sender"], row["recipient"], key=row["id"],
                       amount=row["amount_minor"], at=row["settled_at"])
    frontier = deque([(recipient, (recipient,), (), now - 86400, -1)])
    longest, cycle = (), ()
    examined = 0
    truncated = False
    while frontier and examined < 1024:
        node, path, ids, previous_at, first_at = frontier.popleft()
        if len(ids) > len(longest):
            longest = ids
        if len(ids) == 5:
            continue
        adjacent = sorted(graph.out_edges(node, keys=True, data=True),
                          key=lambda edge: (edge[3]["at"], edge[2]), reverse=True)
        truncated |= len(adjacent) > 24
        for _, target, key, data in adjacent[:24]:
            examined += 1
            at = data["at"]
            if at < previous_at or (first_at >= 0 and at - first_at > 3600):
                continue
            if target == recipient:
                cycle = (*ids, key)
            elif target not in path:
                frontier.append((target, (*path, target), (*ids, key), at, at if first_at < 0 else first_at))
    truncated |= bool(frontier)
    last_hour = now - 3600
    incoming = sum(d["amount"] for _, _, d in graph.in_edges(recipient, data=True) if d["at"] >= last_hour)
    outgoing = sum(d["amount"] for _, _, d in graph.out_edges(recipient, data=True) if d["at"] >= last_hour)
    ratio = min(2, outgoing / incoming) if incoming else 0
    score = (25 if age < 15 else 15 if age < 30 else 0)
    score += 60 if len(longest) >= 5 else 35 if len(longest) >= 4 else 20 if len(longest) >= 3 else 0
    score += 40 if cycle else 0
    score += 25 if ratio >= 0.8 else 0
    reasons = []
    if age < 30:
        reasons.append(f"Recipient account age is {age} days.")
    if longest:
        reasons.append(f"Observed a time-ordered downstream path of {len(longest)} transfers.")
    if cycle:
        reasons.append("Observed a directed cycle at the recipient.")
    if ratio >= 0.8:
        reasons.append(f"Recent settled outflow/inflow is {ratio:.2f}.")
    nodes = [recipient] + sorted(set(graph.nodes) - {recipient})
    indexes = {node: index for index, node in enumerate(nodes)}
    features = [
        [math.log1p(graph.in_degree(node)), math.log1p(graph.out_degree(node)),
         min(age, 365) / 365 if node == recipient else 0.0, float(node == recipient)]
        for node in nodes
    ]
    edges = [(indexes[u], indexes[v]) for u, v in graph.edges()]
    return {"score": min(100, score), "reasons": reasons, "path": list(longest),
            "cycle": list(cycle), "recent_flow_ratio": ratio, "truncated": truncated,
            "watermark": now, "features": features, "edge_index": edges,
            "nodes": [{"data": {"id": node, "label": node}} for node in nodes],
            "edges": [{"data": {"id": key, "source": u, "target": v, "amount_minor": data["amount"]}}
                      for u, v, key, data in graph.edges(keys=True, data=True)]}


def context(db, account, now, *, before_only=False):
    upper = math.nextafter(now, -math.inf) if before_only else now
    frontier, visited, edges = {account}, set(), {}
    truncated = False
    for _ in range(5):
        next_frontier = set()
        for node in sorted(frontier - visited)[:48]:
            visited.add(node)
            for column in ("sender", "recipient"):
                rows = db.execute(
                    f"SELECT * FROM settled WHERE {column}=? AND settled_at BETWEEN ? AND ? "
                    "ORDER BY settled_at DESC, id LIMIT 25", (node, now - 86400, upper)).fetchall()
                bound = 24 if column == "sender" else 12
                truncated |= len(rows) > bound
                for row in rows[:bound]:
                    if len(edges) >= 256 and row["id"] not in edges:
                        return list(edges.values()), True
                    edges[row["id"]] = row
                    if column == "sender":
                        next_frontier.add(row["recipient"])
        truncated |= len(frontier - visited) > 0
        frontier = next_frontier
    return list(edges.values()), truncated
