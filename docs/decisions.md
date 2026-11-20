# Decisions and open inputs

| ID | Status | Design |
|---|---|---|
| D01 | Superseded target | The earlier diagram and narrative describe the payment-plane prototype. |
| D02 | Accepted | The optional Redis evidence cache is separate from Redis Streams job delivery. The durable ledger and outbox own money state and case events. |
| D03 | Accepted | Use bounded case-scoped MCP reads with server validation. Analyst adjudication supplies evaluation labels. |
| D04 | Proposed refinement | Separate real-time auth, rolling inference and async SOC budgets. Measure tail latency and coverage. |
| D05 | Open before integrated payment work | Identify rail sandbox, challenge provider, identity roles and authoritative account data. Approve degraded behavior by channel. |
| D06 | Open before dataset collection | Approve consent, retention and evidence access. Verify dataset and checkpoint rights, language coverage and quality targets. |
| D07 | Open before release gate | Agree operational concurrency, hardware and SLO measurement boundary, acceptable false holds, detection targets and rollout owner. |
| D08 | Accepted | [Figure 1](agentic.pdf) is the target. Keep the payment gateway deterministic and run SOC orchestration from committed events. |
| D09 | Accepted for the sandbox | Use SQLite and a local state machine by default. Offer Postgres, Redis Streams, LangGraph and FastMCP as service-backed configurations. |
| D10 | Accepted for the sandbox | Start at Tier 0. Tier 1 uses state, confidence, risk, caps and a kill switch. Tier 2 requires human approval. |

For each accepted decision record date, owner, alternatives, reasoning, implications and affected milestone gates. [Figure 1](agentic.pdf)
