# Agentic SOC implementation phases

[Figure 1 in agentic.pdf](agentic.pdf) is the acceptance baseline. [Traceability](traceability.md) maps diagram components to phase evidence.

| Phase | Work | Exit check | Status |
|---|---|---|---|
| A0 | Baseline the real-time plane and document ownership | Payment, missingness, challenge, block and idempotency checks pass | Sandbox verified |
| A1 | Transactional outbox, independent case worker and recovery | Atomic enqueue, duplicate delivery, lease expiry, retry and restart work | SQLite verified |
| A2 | MCP tools and Triage, Investigator, Decision and Reporter workflow | Scoped tools, cited verdicts, provider fallback and redacted tool audit | Local orchestrator and MCP verified. SDK variants need installed dependencies. |
| A3 | Analyst timeline, action proposals, approvals and tier enforcement | Kill switch, limits, version checks, authorization and replay protect the ledger | Sandbox API and WebSocket verified. Frontend builds. |
| A4 | Monitor, 30-day watches, alerts, metrics and feedback | Watches survive restart, relevant signals reopen cases and adjudicated outcomes are exportable | Sandbox verified, including sampled benign closure |
| A5 | Redis Streams and Postgres rollout path | Publish and replay events, migrate an isolated ledger, verify data and action parity | Adapters implemented. Redis transport double passed. Live service checks remain open. |
| A6 | Integration rehearsal | Run unit tests first, then exercise payment → event → MCP investigation → analyst and watch flows | In-process rehearsal passed. Live browser and service checks remain open. |

Start with SQLite and read-only autonomy. Introduce reversible sandbox actions after the action gate has been verified. Use the release gates in [Harness](harness.md) for each phase.
