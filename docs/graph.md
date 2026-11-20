# Graph engineering

The scoring pipeline belongs to the payment plane in [Figure 1](agentic.pdf). The SOC reads versioned evidence through scoped MCP tools. Decision-time snapshots remain auditable.

Build a rebuildable directed multigraph from a durable ledger. Key edges by transaction ID and preserve both event and ingestion time. Store amount, currency, rail and lifecycle. Keep attempts separate from settled money flow. Use point-in-time account features and tenant scope.

Score a proposed transfer against an as-of snapshot. Overlay the candidate temporarily when testing topology. Traverse up to five directed edges with recency, fan-out, node and time bounds. Detect cycles with path-local membership. Require event ordering for a rapid dispersion claim. Calculate inflow, outflow and elapsed time from the same bounded ledger window. Emit path IDs, truncation flags and graph watermark. Cache by relevant scope, watermark and feature version. Deduplicate and reconcile late events.

Use past-only features and time/account-group splits for GNN training. Include direction, age, velocity and edge timing. Compare recall at an agreed false-positive cap to NetworkX and tabular baselines. Synthetic rings seed development and ground truth requires reviewed cases. Export the feature schema and calibration alongside the checkpoint.

Test repeated account pairs, exact five-edge boundaries, loops, benign hubs, held attempts, duplicates, out-of-order data, restart rebuild and bounded latency. Render the same evidence snapshot in SOC.
