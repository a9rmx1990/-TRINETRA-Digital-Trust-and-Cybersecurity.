# Runtime contracts

## Real-time payment plane

| Operation | Data and rules |
|---|---|
| Call session | Owner-scoped bearer credential and consent create a short-lived call ID. SDP negotiates WebRTC or the browser posts bounded PCM. Raw audio expires with the session. |
| Evidence snapshot | Window IDs, coverage offsets, model status and version, graph watermark, diagnostic evidence and policy version accompany the recorded decision. Investigation reads the committed snapshot. |
| Payment | Owner, idempotency key, recipient, integer minor units, payment channel, optional call ID and remarks. Repeated keys with the same request replay the original payment. Conflicting requests return 409. |
| Gateway | ALLOW settles in the sandbox. STEP_UP requires a valid, expiring challenge. HOLD awaits analyst disposition. BLOCK records an active account restriction. Restrictions and active temporary holds are checked before settlement. |
| Case and event | Flagged transfers create versioned cases and append ordered events. Case API reads current state. WebSocket notices carry a cursor and changed payment IDs for replay. |

## SOC plane

- **Handoff.** A case-changing event and its outbox entry commit together. Each job has a unique ID, case ID, case version, trigger, due time and lease. Redis Streams carries versioned job IDs. The relational ledger handles duplicate delivery, retries and exhaustion.
- **Tools.** MCP scopes carry case ID and role in trusted server context. Tools validate named arguments and enforce access per role. Investigator tools are bounded reads. Audits append tool, role, run, arguments, outcome, result fingerprint, and safe evidence fields.
- **Verdict.** The structured payload includes case ID, fraud/suspicious/benign label, confidence, suggested action, evidence IDs and a rationale. The decision stage checks every reference against the evidence retrieved for that run. Invalid verdicts produce a review-only result.
- **Actions.** The action gate looks up the server-stored proposal, checks current case version and payment state, applies the configured tier and kill switch, and records the outcome in one transaction. Retrying a resolved proposal returns its outcome. Approval and rejection require analyst authentication and a rationale. The verification code is available to the authorized analyst and the ledger stores its hash.
- **Watch.** A case has a persistent due time, last event cursor, and 30-day horizon. New material signals for the recipient reopen case review. Settlement remains terminal.
- **Reporting.** Analyst alerts and structured verdict metrics enter the reporting table. Analyst overrides append human labels. Analytics datasets and evaluation examples have analyst-scoped endpoints.

[Architecture](architecture.md) · [Operations](operations.md) · [Harness](harness.md)
