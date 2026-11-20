# Operations and data controls

## Local sandbox

Use a distinct SQLite ledger per demo or test. Set the analyst key on the backend and use it in the analyst console. WebRTC requires localhost or HTTPS and approved ICE configuration. Keep capture bounded and expire audio at session close. Transcripts are excluded from provider requests by default. The opt-in path filters instruction-like text and sends a bounded excerpt with read-only tools.

The worker can run inside FastAPI or as a dedicated process. The payment gate owns settlement. The worker reads the outbox and resumes expired leases on restart. A job that exhausts its bounded retries is retained as failed and appears in SOC analytics. The shutdown path and Redis outages preserve the relational jobs.

## Agent actions

Start with Tier 0. Raise the maximum configured tier on an isolated ledger when testing actions. The analyst can pause and resume configured agent actions. The ledger verifies case version, current state, confidence and trusted risk for automatic actions, an hourly cap, and active restrictions. Analysts can continue manual case operations while agent actions are paused. The default hold expires after 15 minutes. Agent-issued step-up codes expire after three minutes and are fetched through the analyst console for the sandbox handoff.

Review logs using job IDs, case IDs and event cursors. Keep challenge proofs, bearer credentials, raw audio and transcript text out of audit logs. Audit records store safe evidence references and output fingerprints. Keep provider access and database access scoped to the operating environment.

## Redis and Postgres rollout

1. Run the optional service integration checks with an isolated Redis service and a dedicated Postgres database that permits creation of a temporary test schema.
2. Back up the SQLite ledger and stop both API and SOC workers before migration. Migrate into an empty Postgres schema and compare recorded counts. Retain the SQLite backup for recovery.
3. Start the API and worker against the same Postgres URL. Set a dedicated Redis Streams URL for job delivery and check queue lag, case cursors and action audit. The audio snapshot cache uses its own setting.
4. Rehearse a Redis outage, duplicate message delivery, worker restart, and rollback on a sandbox copy. Monitor payment latency and SOC queue latency independently. The payment-plane design targets a p95 below 150 ms at an agreed load. Keep real settlement and external notifications behind separate deployment integration.

[Runtime configuration](runtime.md) · [Harness](harness.md)
