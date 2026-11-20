# Traceability to agentic.pdf

[Figure 1](agentic.pdf) is the acceptance baseline. Service-backed checks and local integration evidence are tracked separately.

| Figure 1 component | Phase | Implementation and verification |
|---|---|---|
| Caller portal, call and payment APIs | A0 | React and FastAPI v2. Sandbox integration exercises PCM, ownership, and idempotency. Browser microphone and WebRTC need a network-capable host. |
| Voice spoof, coercion, remarks, GNN, policy | A0 | Existing model adapters and deterministic policy. Sandbox tests exercise missingness and distinct learned scores. Promotion still requires reviewed artifacts and evaluation. |
| Payment gateway | A0, A3 | SQLite sandbox settlement, verified challenges, holds, blocks, restrictions and version checks. Unit and integration coverage in the sandbox harness. |
| Database | A1, A5 | SQLite is the default. Optional Postgres adapter and migration tool preserve IDs and cursors. Live Postgres verification requires the isolated service. |
| Outbox and event bus | A1, A5 | Transactional enqueue, leases, retry, recovery and Stream job IDs. SQLite tests cover rollback and reclaim. Broker-contract tests cover duplicate delivery. Live Redis verification requires the isolated service. |
| Scheduler and Monitor | A4 | Durable daily checks through 30 days. Verified restart, linked signals, and case-only reopening. |
| Orchestrator, Triage, Investigator, Decision, Reporter | A2, A4 | Local state machine, optional LangGraph engine. Verified provider tool calls, fallbacks, cited verdicts, reports and analytics using a stubbed provider. |
| Guardrails | A2, A3 | Tool schemas, role allowlists, citation scope, transcript filtering, approval tiers, hourly limits, append-only audit and persistent kill switch. |
| Case, evidence, graph and model MCP | A2 | Shared case-scoped JSON-RPC handlers and read-only stdio. Native MCP is exercised in-process and over stdio. FastMCP is an optional stdio adapter. |
| Action, notify and BI MCP | A3, A4 | Internal action execution, analyst alerts and structured analytics reports. Outputs remain within the sandbox. |
| Analyst dashboard | A3, A4 | Agent timeline, evidence IDs, approval, rejection, adjudication, verification code handoff and watch status. Build checks types. In-process WebSocket test verifies replay. |
| Memory and learning | A4, A6 | Similar closed cases from score profiles and analyst-adjudicated evaluation export. Optional benign closure applies only to verified low-risk cases and samples analyst QA. Live calibration is a rollout gate. |

[Phases](plan.md) · [Harness](harness.md) · [Runtime](runtime.md)
