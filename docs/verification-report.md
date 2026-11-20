# Verification report

Build: TRINETRA Digital Trust and Cybersecurity v2.0.0 (first build of this codebase, no VCS commit). Policy `2026.11-r1`.
Run date: 20 Nov 2026, Asia/Calcutta.
Environment: Linux on 2 vCPU, Python 3.13, Node 22.23, PostgreSQL 16.15, Redis 7.0.15 with redis-py 8.1, Google Chrome headless via Playwright 1.65.
Isolation: every run used a temporary SQLite file or a dedicated PostgreSQL database. The normal product was never seeded.

## Results by gate

| Gate | Result | Evidence |
|---|---|---|
| 1. Ownership and inputs | **Pass** | `test_fresh_start_is_empty`, `test_ownership_isolation`; browser test 1 checks empty start, reload recovery, a second session seeing nothing, and axe with zero violations |
| 2. Payment and evidence | **Pass** | Capture refusals (omitted, foreign, silent, unfinished, expired, no consent) create 0 payments, cases, settlements and jobs. Also covered: idempotent replay after expiry, key conflict, capture reuse, restriction BLOCK, fan-in HOLD, challenge expiry, attempt cap, hold-versus-verify, release |
| 3. SOC and UI | **Pass** | Browser test 2 runs submit, step-up, analyst approval, code, verify, settled history, then chart bar to rows. `test_chart_bucket_reconciles_to_sql` matches bucket payment IDs to SQL. Axe on the SOC case view: zero WCAG 2 A/AA violations |
| 4. Parallel services | **Pass** | All DB tests run on SQLite and live PostgreSQL. Multi-process load profile, crash drill and migration rehearsal are below |
| 5. Model acceptance | **Open** | Hugging Face is unreachable from this build environment, so no checkpoint was downloaded or measured. Every model signal reports `unavailable`, and the policy steps up as specified. The harness is ready: `backend/eval/run_eval.py` |
| 6. Rehearsal | **Pass for the local profile** | `scripts/test-all.sh` steps rerun from a clean state, with all passing as below |

## Automated suites

| Suite | Pass | Fail | Skip | Notes |
|---|---|---|---|---|
| Backend, SQLite and live PostgreSQL (`TRINETRA_TEST_PG_URL` set) | 76 | 0 | 2 | The 2 skips are the SQLite variants of tests that need overlapping writers; both pass on PostgreSQL |
| Backend, SQLite only | 49 | 0 | 29 | The skips are the PostgreSQL parameterizations |
| Frontend typecheck (`tsc -b`, strict) | pass | | | |
| Frontend unit (`node --test`) | 4 | 0 | 0 | INR grouping, amount parsing to paise, typing grouping, masking and durations |
| Frontend production build | pass | | | Customer bundle 75 KB gzip; SOC lazy-loaded at 164 KB gzip (Cytoscape) |
| Browser (real Chrome, fake microphone) | 5 | 0 | 0 | Streamed speech, microphone denial, silence rejection, full customer-to-analyst loop, narrow-screen case route |

## Concurrency and recovery (live PostgreSQL)

| Scenario | Outcome |
|---|---|
| 100 simultaneous retries of one key (in-process, 20 threads) | 1 payment, at most 1 evaluation event, outbox equal to events |
| 100 simultaneous retries over HTTP against 2 API processes | 1 × 201, 99 × 200, 1 distinct payment ID |
| 20 independent clients, then 4 workers draining | 20 payments, 20 jobs done, no case investigated twice |
| Release versus restriction race | Exactly one applies; final state is SETTLED with 1 settlement or BLOCKED with 0 |
| Correct code with 10 concurrent verifications | 1 `verified`, 1 settlement |
| Two approvals against the same case version | 1 applies, 1 gets `stale_version`, 1 challenge exists |
| Expired lease versus replacement worker | Replacement commits; the stale worker raises `FenceLost`; 1 `investigation_completed` |
| Duplicate trigger enqueue and redelivery after completion | Collapses to one job; redelivery does nothing |
| Out-of-order commits (first allocated, last committed) | Delivered after the earlier commit; delivery cursor is gap-free |
| Unrelated payment while another payment and case are row-locked | Commits in under 3 s, no blocking (SQLite serializes this, as recorded) |
| SQLite to PostgreSQL migration with settled transfers | All ID sets, counts, case and payment states and event links match; settlement total ₹6,000.00 preserved |

**Outage drill.** Setup: 2 API processes and 2 worker processes on PostgreSQL with Redis.

1. Killed both worker processes with SIGKILL during load. 30 jobs were pending.
2. Restarted PostgreSQL, and restarted Redis with all data lost.
3. Restarted the workers. All jobs drained and all events were delivered about 2.2 s after the database restart.
4. Checked integrity: 0 duplicate investigations, 0 duplicate payments per key, 0 undelivered events, no cursor gap.

The first run of this drill found a defect: the API-process dispatcher held a dead connection after the database restart, leaving 30 events undelivered. The database layer now discards broken connections and retries. The drill was rerun with the result above.

## Latency and throughput

**Load profile.** PostgreSQL with 2 API processes, 2 worker processes (4 SOC workers), Redis audio cache and hints, 20 clients × 5 transfers, no models installed, 2 vCPU shared by every process.

| Stage | p50 | p95 | p99 | n |
|---|---|---|---|---|
| Capture upload (3 s of PCM in 6 chunks) | 312 ms | 430 ms | 467 ms | 100 |
| Capture finish (quality measurement and stub adapters) | 72 ms | 143 ms | 181 ms | 100 |
| Payment policy and commit (`POST /payments`) | 124 ms | 207 ms | 224 ms | 100 |
| Asynchronous investigation (case created to report, from ledger timestamps) | 161 ms | 308 ms | 323 ms | 100 |

Other results:

- Throughput: 31.4 submissions/s.
- Worker backlog drained within about 5 s of the last submission, with 0 retries and 0 deadlocks (`pg_stat_database`).
- Ledger checks after the run: 0 duplicate settlements and a gap-free cursor.

**Single-client payment path** (`POST /payments`, PostgreSQL, 1 API process): 26 ms on the first call after restart; warm calls 9 ms p50 and 22 ms p95 (n = 20).

**On the 150 ms p95 objective:** it is met at single-client load and missed (207 ms) with 20 concurrent clients on this 2-vCPU host, where API, workers, PostgreSQL, Redis and the load generator all compete for the same cores. No load level has been agreed, so this is reported, not claimed. With models installed, add the measured inference time to capture finish.

## Known limitations and open items

- **Models (gate 5 open).**
  - No checkpoint is installed or evaluated, and no labelled evaluation data was available.
  - Reviewed Kannada payment conversations and matched benign cases still need sourcing.
  - Promote a signal to `enforce: true` only after `run_eval.py` reports agreed limits with sufficient per-language samples.
  - The wav2vec2 detector's CC BY-NC 4.0 license needs review before any redistribution or commercial use.
- **WebRTC.** `POST /calls/{id}/offer` returns 501. PCM streaming over HTTP is the supported transport.
- **Optional adapters.** No loopback LLM, LangGraph or FastMCP adapter is included. The deterministic local evidence report always runs, and the read-only stdio MCP server is included.
- **Manual accessibility inspection.**
  - Automated axe checks pass on both workspaces.
  - Keyboard operation is built in: real buttons and links throughout, a native modal `<dialog>` that returns focus to its opener, keyboard-operable chart bars and a table equivalent for every chart. Reduced motion is honored.
  - No human has walked through keyboard-only use, 200% zoom or a screen reader yet.
- **Commit-outcome ambiguity.** If a PostgreSQL connection drops during COMMIT, a write is retried. Payments, settlements, outbox jobs and challenges are protected by unique keys and fences, but a case event could be appended twice in that narrow window.
- **Sandbox identity.** A customer session is a browser-held bearer token, with no login or recovery. Analysts share one passcode and a single scope (`sandbox`).
