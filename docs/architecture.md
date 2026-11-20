# Target architecture

[Figure 1 on page 3 of agentic.pdf](agentic.pdf) is TRINETRA’s primary design. The deterministic payment plane owns risk decisions and settlement. The SOC plane consumes committed case events, investigates and reports through case-scoped MCP tools, and submits proposals through an authorization gate.

~~~mermaid
flowchart TD
    subgraph Payment["Real-time payment plane"]
        Portal["Caller portal"] --> APIs["Call session and payment APIs"]
        APIs --> Signals["Voice spoof · speech coercion · remarks · recipient GNN"]
        Signals --> Policy["Deterministic risk policy"]
        Policy --> Gate["Payment gateway"]
    end
    Gate --> Ledger[("Ledger · cases · evidence · audit")]
    Ledger --> Delivery["Transactional outbox · optional Redis Streams"]
    Ledger --> Scheduler["Durable 30-day watches"]
    Delivery --> Workflow
    Scheduler --> Workflow
    subgraph Agent["Asynchronous SOC plane"]
        Workflow["Orchestrator"]
        Workflow --> Roles["Triage · Investigator · Decision · Monitor · Reporter"]
        Roles --> Tools["Scoped MCP tools · schemas · audit"]
    end
    Tools --> Review["Analyst console · timeline · approve · reject · override"]
    Tools --> Actions["Action gate · tier · state · limits · kill switch"]
    Review --> Actions
    Actions --> Ledger
~~~

## Payment plane

The browser sends WebRTC or 16 kHz HTTP PCM to FastAPI. Rolling speech windows drive spoof and Whisper inference. XLM-R screens transcript and typed remarks. NetworkX and the GNN score bounded recipient history. The policy uses version-matched fusion or the strongest eligible learned score and applies hard overrides and missing-evidence rules. The gateway enforces ALLOW, STEP_UP, HOLD and BLOCK in the sandbox ledger. Payment scoring reads evidence only. Operator and agent effects enter through transactional commands.

## Agent plane

| Role | Responsibility | Tool scope |
|---|---|---|
| Triage | Read the case and link bounded prior activity. Rank work by case priority. | Case and history |
| Investigator | Inspect call evidence, graph edges, model scores, and similar closed cases. A configured provider can call bounded read tools. | Case, evidence, graph and model tools |
| Decision | Validate verdict shape, confidence, case identity, and evidence IDs. | Structured inputs |
| Monitor | Schedule daily checks through the 30-day watch horizon and reopen cases with material related signals. | Scheduler |
| Reporter | Draft an analyst alert and prepare analytics fields. | Notify and BI tools |

SQLite is the default ledger. Postgres is configurable. The relational outbox owns job state, retries, and leases. Redis Streams carries job IDs when enabled. The case WebSocket replays cursor-based updates from committed events.

Tier 0 supports investigation and reporting. Tier 1 can issue a verification challenge, add a time-limited hold to an eligible unsettled transfer, or expedite a watch. Tier 2 requires an analyst to approve restrictions or a report. The kill switch pauses agent effects. The ledger rechecks case version, current payment state, caps, and eligibility when it applies an action.

[Runtime and limits](runtime.md) · [Contracts](contracts.md) · [Verification](harness.md) · [Traceability](traceability.md)
