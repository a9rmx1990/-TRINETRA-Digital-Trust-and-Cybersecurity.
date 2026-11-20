"""Graph Intelligence Engine: Real-Time Mule-Ring & Topological Laundering Detection.

Uses NetworkX directed multigraphs to evaluate multi-hop transaction layering,
dispersion velocity ratios (V_disp), directed cycles, and high fan-out mule nodes.
"""

import time
import networkx as nx
from typing import Tuple, List, Dict, Any, Optional
from app.schemas import GraphDiagnostics

class GraphIntelligenceEngine:
    def __init__(self):
        # In-memory directed graph of accounts and transactions
        self.graph = nx.DiGraph()
        self.quarantined_accounts: set[str] = set()

    def reset(self):
        """Reset in-memory graph state (used for testing and demo resets)."""
        self.graph.clear()
        self.quarantined_accounts.clear()

    def add_transaction(
        self,
        sender: str,
        recipient: str,
        amount: float,
        timestamp: Optional[float] = None,
        tx_id: Optional[str] = None,
        recipient_age_days: int = 365
    ):
        """Inserts a transaction edge and updates node financial telemetry."""
        now = timestamp if timestamp is not None else time.time()
        tx_ref = tx_id or f"TX-{int(now * 1000)}"

        # Ensure sender node exists
        if not self.graph.has_node(sender):
            self.graph.add_node(sender, age_days=365, total_in=0.0, total_out=0.0, first_seen=now)
        
        # Ensure recipient node exists
        if not self.graph.has_node(recipient):
            self.graph.add_node(recipient, age_days=recipient_age_days, total_in=0.0, total_out=0.0, first_seen=now)

        # Update node balances
        self.graph.nodes[sender]["total_out"] += amount
        self.graph.nodes[recipient]["total_in"] += amount

        # Add directed edge
        self.graph.add_edge(
            sender,
            recipient,
            amount=amount,
            timestamp=now,
            tx_id=tx_ref
        )

    def calculate_dispersion_velocity(self, account: str) -> float:
        """Computes V_disp = (Outflow / (Inflow + eps)) * (1 / (delta_t_hours + eps)).
        A high value indicates immediate pass-through cashing out (mule behavior).
        """
        if not self.graph.has_node(account):
            return 0.0

        node_data = self.graph.nodes[account]
        total_in = node_data.get("total_in", 0.0)
        total_out = node_data.get("total_out", 0.0)

        if total_in <= 0.0 or total_out <= 0.0:
            return 0.0

        # Calculate time delta in hours since first transaction
        first_seen = node_data.get("first_seen", time.time())
        delta_hours = max(0.005, (time.time() - first_seen) / 3600.0)  # Min ~18 seconds floor

        outflow_ratio = min(2.0, total_out / (total_in + 1e-6))
        # Velocity is high if funds leave rapidly
        velocity = (outflow_ratio / delta_hours)
        return float(round(velocity, 2))

    def detect_cycles(self, root_account: str, max_depth: int = 5) -> List[List[str]]:
        """Finds directed circular fund routing loops starting/ending near root_account."""
        if not self.graph.has_node(root_account):
            return []

        # Extract local ego subgraph up to max_depth
        sub_nodes = set([root_account])
        current_layer = {root_account}
        for _ in range(max_depth):
            next_layer = set()
            for n in current_layer:
                next_layer.update(self.graph.successors(n))
            sub_nodes.update(next_layer)
            current_layer = next_layer
            if not current_layer:
                break

        ego_subgraph = self.graph.subgraph(sub_nodes)
        cycles = []
        try:
            for cycle in nx.simple_cycles(ego_subgraph):
                if len(cycle) <= max_depth and root_account in cycle:
                    cycles.append(cycle)
        except Exception:
            pass

        return cycles

    def trace_hop_depth(self, start_account: str, max_hops: int = 5) -> int:
        """Finds the maximum downstream chain depth of sequential transfers."""
        if not self.graph.has_node(start_account):
            return 1

        visited = set()
        def dfs(node: str, depth: int) -> int:
            if depth >= max_hops or node in visited:
                return depth
            visited.add(node)
            max_d = depth
            for succ in self.graph.successors(node):
                max_d = max(max_d, dfs(succ, depth + 1))
            visited.remove(node)
            return max_d

        return dfs(start_account, 1)

    def extract_subgraph_cytoscape(self, focus_account: str, radius: int = 2) -> Dict[str, Any]:
        """Serializes local neighborhood into Cytoscape.js format for frontend SOC view."""
        if not self.graph.has_node(focus_account):
            return {"nodes": [{"data": {"id": focus_account, "label": focus_account, "type": "standard"}}], "edges": []}

        # Ego subgraph with undirected radius
        ego_nodes = set([focus_account])
        for _ in range(radius):
            expansion = set()
            for n in ego_nodes:
                expansion.update(self.graph.successors(n))
                expansion.update(self.graph.predecessors(n))
            ego_nodes.update(expansion)

        nodes = []
        for n in ego_nodes:
            is_quarantined = n in self.quarantined_accounts
            age = self.graph.nodes[n].get("age_days", 365)
            node_type = "quarantined" if is_quarantined else ("new_account" if age < 30 else "standard")
            nodes.append({
                "data": {
                    "id": n,
                    "label": n,
                    "type": node_type,
                    "age_days": age,
                    "total_in": self.graph.nodes[n].get("total_in", 0.0),
                    "total_out": self.graph.nodes[n].get("total_out", 0.0)
                }
            })

        edges = []
        for u, v, data in self.graph.edges(ego_nodes, data=True):
            if u in ego_nodes and v in ego_nodes:
                edges.append({
                    "data": {
                        "id": f"e_{u}_{v}_{data.get('tx_id', '')}",
                        "source": u,
                        "target": v,
                        "amount": data.get("amount", 0.0),
                        "tx_id": data.get("tx_id", "")
                    }
                })

        return {"nodes": nodes, "edges": edges}

    def analyze(
        self,
        sender: str,
        recipient: str,
        amount: float,
        recipient_age_days: int = 365,
        tx_id: Optional[str] = None
    ) -> Tuple[float, GraphDiagnostics, List[str], Dict[str, Any]]:
        """Evaluates transaction topology and returns (score, diagnostics, reasons, cytoscape_graph)."""
        # Register the prospective transaction into the graph
        self.add_transaction(
            sender=sender,
            recipient=recipient,
            amount=amount,
            recipient_age_days=recipient_age_days,
            tx_id=tx_id
        )

        reasons = []
        anomaly_points = 0.0

        # Check 1: Direct transfer to an already quarantined account
        if recipient in self.quarantined_accounts or sender in self.quarantined_accounts:
            anomaly_points += 100.0
            reasons.append("Account is currently on the active quarantine/freeze list.")

        # Check 2: New Account Age Risk (< 30 days old)
        if recipient_age_days < 15:
            anomaly_points += 25.0
            reasons.append(f"Destination account is newly provisioned ({recipient_age_days} days old).")
        elif recipient_age_days < 30:
            anomaly_points += 15.0

        # Check 3: Downstream Hop Depth Analysis
        hop_depth = self.trace_hop_depth(recipient, max_hops=5)
        if hop_depth >= 4:
            anomaly_points += 35.0
            reasons.append(f"Rapid multi-hop dispersion chain detected ({hop_depth} hops).")
        elif hop_depth >= 3:
            anomaly_points += 20.0
            reasons.append(f"Extended multi-hop transfer path detected ({hop_depth} hops).")

        # Check 4: Directed Circular Laundering (Cycles)
        cycles = self.detect_cycles(recipient, max_depth=5)
        cycle_detected = len(cycles) > 0
        if cycle_detected:
            anomaly_points += 40.0
            cycle_repr = " -> ".join(cycles[0] + [cycles[0][0]])
            reasons.append(f"Circular fund laundering loop detected: {cycle_repr}.")

        # Check 5: Dispersion Velocity (Outflow / Inflow speed)
        disp_velocity = self.calculate_dispersion_velocity(recipient)
        if disp_velocity > 1.5:
            anomaly_points += 30.0
            reasons.append(f"High fund dispersion velocity (V_disp={disp_velocity}); funds draining immediately upon receipt.")
        elif disp_velocity > 0.8:
            anomaly_points += 15.0

        # Calculate final bounded score
        graph_score = min(100.0, max(0.0, anomaly_points))
        is_mule = graph_score >= 60.0

        # If critical mule risk, auto-quarantine recipient node
        quarantined_list = []
        if graph_score >= 70.0:
            self.quarantined_accounts.add(recipient)
            quarantined_list.append(recipient)
            reasons.append(f"Destination node [{recipient}] locked and flagged for AML review.")

        if not reasons:
            reasons.append("Normal low-degree, single-hop transaction topology.")

        diagnostics = GraphDiagnostics(
            is_mule_ring=is_mule,
            hop_count=hop_depth,
            dispersion_velocity=disp_velocity,
            cycle_detected=cycle_detected,
            quarantined_nodes=quarantined_list
        )

        cytoscape_data = self.extract_subgraph_cytoscape(recipient, radius=2)

        return (round(graph_score, 1), diagnostics, reasons, cytoscape_data)

    def quarantine_account(self, account: str):
        self.quarantined_accounts.add(account)

    def release_quarantine(self, account: str):
        self.quarantined_accounts.discard(account)
