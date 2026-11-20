# Operations

## Processes

| Process | Command | Notes |
|---|---|---|
| API | `uvicorn app.main:app --workers N` | Each process runs one delivery dispatcher (serialized on the counter row) |
| SOC worker | `python -m app.soc.worker` | `TRINETRA_WORKERS` threads per process; claims with `FOR UPDATE SKIP LOCKED` |
| Read-only MCP | `python tools/mcp_stdio.py --actor NAME` | Case-scoped read tools only; every call audited |

With more than one API process, set `TRINETRA_AUDIO_CACHE_URL` so PCM chunks can land on any process, and share `TRINETRA_SERVER_SECRET` (or the data directory) so analyst tokens validate everywhere.

## Concurrency design

- Inference runs outside write transactions, bounded by `TRINETRA_INFERENCE_CONCURRENCY` and `TRINETRA_INFERENCE_TIMEOUT_S`.
- SQLite uses WAL, `BEGIN IMMEDIATE` (one writer at a time), `busy_timeout` and bounded retry.
- On PostgreSQL there is no database-wide lock. Coordination relies on:
  - database-enforced uniqueness: `(owner_id, idem_key)`, `settlements.payment_id`, `calls.payment_id` and `outbox.trigger_key`
  - row locks taken in a consistent order: account, then counterparty, then call for payments; case, then payment for SOC actions
  - transaction-scoped keyed advisory locks where a row may not exist yet (counterparty registration, restrictions)
- Deadlocks, serialization failures and lost connections are retried with bounded backoff using the original command key. A broken connection is discarded and reopened.
- Outbox claims use `FOR UPDATE SKIP LOCKED`. A lease token plus the case version read at start fence stale workers, and the job is acknowledged in the same transaction as its effects.
- Delivery order follows commit visibility. A short serialized dispatcher assigns `delivery_seq` to committed events, so a transaction that starts first and commits last is delivered last, and the cursor has no gaps.

## Rollout

1. Run SQLite parity: `pytest -q`, then `scripts/e2e.sh`.
2. Stop the API and workers to quiesce the database.
3. Run `python tools/migrate_sqlite_to_postgres.py <sqlite file> <postgres url>`. The target must be empty. The tool reports matching counts, ID sets, case and payment states, event links and settlement totals, and exits non-zero on any mismatch.
4. Start the API processes and workers against PostgreSQL.
5. To roll back, set `TRINETRA_DATABASE_URL` back to the untouched SQLite file and restart.

Redis is optional. If it is unavailable, workers keep polling SQL and job hints are skipped. Only the shared audio cache depends on Redis, and only in multi-process deployments.

## Legacy and test data

Rows tagged `legacy_demo = 1` are excluded from customer views, the queue and analytics. Tests use temporary databases and hand-authored records. The normal running product is never seeded.

## Logs

Credentials, verification codes and raw audio are never logged. Analyst rationale, transcript and remark text are redacted in the tool audit arguments. Verification codes exist only as salted HMAC hashes.
