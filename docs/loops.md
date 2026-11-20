# Loop engineering

## Build and verification loop

Select a milestone invariant → capture baseline → implement a reviewable slice → run targeted checks → inspect failures and traces → correct or record a blocker → run the milestone gate → checkpoint. Stop when the exit evidence exists or a named dependency blocks further progress. Retry transient failures with a bound, and preserve the initial failure before retry.

## Runtime graph and feedback loops

Media → window → inference → session update repeats while the call is live. Bound queues, coalesce stale work, preserve coverage gaps and discard work after expiration. Payment reads a snapshot once per decision attempt. Case changes commit to the outbox and trigger the scoped MCP workflow. A daily scheduler checks watched recipients for 30 days using a durable event cursor.

Analyst disposition and sampled benign closure → independent adjudication and deduplication → labeled example → dataset version → offline training → evaluation → shadow scoring → reviewed promotion → drift monitoring or rollback. RELEASE and CONFIRM_FREEZE are weak feedback signals. Include sampled allows to reduce selection bias and delayed outcomes where available. Review false holds and missed fraud by channel and language. Never auto-promote from analyst actions alone.

Maintain a dependency graph using milestone IDs in the plan. Each evidence packet references prerequisite versions. Reopen affected downstream gates after an incompatible change. [Plan](plan.md) · [Graph](graph.md) · [Harness](harness.md)
