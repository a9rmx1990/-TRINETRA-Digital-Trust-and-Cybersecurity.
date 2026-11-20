# TRINETRA Digital Trust and Cybersecurity

An end-to-end sandbox for protecting banking transfers. The **customer workspace** opens a sandbox account, saves beneficiaries, captures a mandatory voice confirmation and guides the customer through money requests. The **transaction gateway** screens the evidence, enforces restrictions and records the outcome. The **Gemini analyst workspace** provides a case queue, evidence, Gemini findings, and human verification of incoming requests.

Environment label: **Banking sandbox**. No real funds, bank connection, cloud account, paid API or model training is involved. A fresh installation opens empty: every person, transfer, relationship and chart value comes from what users enter.

## Quick start (SQLite, single host)

Requirements: Python 3.12+, Node 22+.

```bash
pip install -r backend/requirements.txt
read -rsp 'Analyst workspace password: ' TRINETRA_ANALYST_WORKSPACE_PASSWORD
export TRINETRA_ANALYST_WORKSPACE_PASSWORD
printf '\n'
./scripts/start.sh
```

Then open:

- Customer workspace at http://127.0.0.1:8000/
- Gemini analyst workspace at http://127.0.0.1:8000/analyst. Sign in as `admin` with the workspace password.

For development with hot reload, run `./scripts/dev.sh` (API on :8000, Vite on :5173).

### A first walkthrough

1. Customer: **Create sandbox account**, then **Add contact** (any 6–18 character reference, for example `HDFC00012345`).
2. Open **Request money**, choose **Request from**, and enter an amount. Continue, agree to voice screening, start and stop the recording, then select **Review request** and submit.
3. Without local models, spoken content cannot be screened, so a first transfer to a new recipient needs additional verification.
4. Gemini analyst: open the case, select **Run analysis**, review the findings, and click **Verify it**.
5. Customer: the sandbox receipt updates automatically and shows **Verified** with an animated checkmark when the incoming transfer settles.
6. A second small transfer (₹5,000 or less) to the same recipient settles immediately.

## Architecture

```
Customer portal (React) ──consent, PCM audio, payment, verification──▶ FastAPI (owner scope)
   │                                                                     │ completed, owned, fresh, usable capture?
   │                                                    no ──▶ refused, nothing written
   │                                                    yes ─▶ local inference (spoof ∥ Whisper → text) ∥ bounded recipient graph
   │                                                           ▼
   │                                          versioned deterministic policy (2026.11-r2)
   │                                                           ▼
   │                SQL transaction: payment + settlement or case + evidence + event + outbox job
   │                                                           ▼
   │                SOC worker (lease, retry, version fence): Triage → Investigator → Decision → Monitor → Reporter
   │                            via case-scoped MCP tools ──▶ guarded action service ──▶ ledger
   ▼                                                           ▼
receipt / history                     post-commit delivery cursor ──▶ WebSocket ──▶ analyst queue, case file, charts
```

| Path | Responsibility |
|---|---|
| `backend/app/customer.py` | Accounts, beneficiaries, voice capture, payment submission, idempotency, settlement, verification |
| `backend/app/inference.py` | Measured capture quality, manifest verification, Whisper/wav2vec2/text adapters, coercion rules |
| `backend/app/graph.py` | NetworkX recipient graph from settled history only (bounded window, depth, nodes) |
| `backend/app/policy.py` | Deterministic policy. The four signal categories are always present, even when unavailable |
| `backend/app/events.py` | Case events, transactional outbox, post-commit delivery ordering, optional Redis hints |
| `backend/app/soc/worker.py` | Outbox claims (`FOR UPDATE SKIP LOCKED` on PostgreSQL), leases, five stages, watches |
| `backend/app/soc/mcp.py` | Case-scoped JSON-RPC tools with per-role allow-lists and redacted audit |
| `backend/app/soc/actions.py` | Version-checked, tiered, rate-limited actions with kill switch and command-key replay |
| `backend/app/soc/views.py` | Queue, case file, event replay, analytics (shared scope, bounds and watermark) |
| `frontend/src/customer/` | Customer workspace (light neutral, navy text, one blue primary action) |
| `frontend/src/analyst/` | Gemini analyst workspace, case evidence, human verification approval, and findings |

### Policy summary (2026.11-r2)

- An active restriction on the sender account, the recipient, or the recipient's own sandbox account results in **BLOCK**.
- **HOLD** only on eligible evidence: a validated (`enforce: true`) model flag, or recipient fan-in (three or more other customers in 7 days) combined with a coercion-rule hit. Review-only scores and inconclusive voice never hold.
- **STEP_UP** applies in these cases:
  - a coercion-rule hit or fan-in alone
  - a first transfer of ₹10,000 or more to a recipient
  - ₹2,00,000 or more
  - review-only model flags
  - inconclusive voice, unscreened spoken content, or an unscreened supplied remark on an incoming request
  - unscreened spoken content on an outgoing transfer, unless the recipient is established and the amount is ₹5,000 or less
- Otherwise **ALLOW**, which settles inside the same transaction.

The analyst workspace shows screening reasons and a suspicion level. Missing
or inconclusive evidence is shown separately from affirmative risk signals.
High suspicion reflects a policy hold or block. Model scores are review
signals and cannot establish the requester’s identity.

### Voice capture

The browser's AudioWorklet streams 16 kHz mono PCM. The server measures speech activity and rejects silence, too-short or clipped audio before any payment exists. Raw audio lives in bounded memory (or the separate Redis audio cache) and is discarded when the call finishes. Only measured results are stored. `POST /payments` refuses a missing, foreign, unfinished, unusable, used or expired capture and creates nothing. An identical retry of an already committed request replays its receipt even after the capture has expired.

## Local models

`backend/models/manifest.json` lists published checkpoints only. Entries stay **unavailable** until downloaded and pinned:

```bash
pip install -r backend/requirements-models.txt
python backend/tools/fetch_models.py      # resolves commit hashes and writes sha256 into the manifest
HF_HUB_OFFLINE=1 ./scripts/start.sh       # inference runs from local storage
```

| Signal | Checkpoint | Default |
|---|---|---|
| Speech to text | Systran/faster-whisper-base (CTranslate2) | review-only |
| Voice authenticity | Bgeorge/deepfake-audio-detector-wav2vec2 (CC BY-NC 4.0: review before redistribution) | inconclusive with diagnostic scores until the conflicting class labels are validated |
| Coercion text | bangta/Scam-detection (English, Vietnamese) | review-only, published threshold 0.69 |
| Coercion text, zero-shot | MoritzLaurer/mDeBERTa-v3-base-mnli-xnli | disabled until evaluated |
| Learned graph | none published with a compatible schema | disabled; deterministic graph evidence used |

Evaluate frozen checkpoints with `backend/eval/run_eval.py` (see its docstring for the data layout). A signal is promoted to `enforce: true` only after its operating limits pass; changing that requires a new policy version.

## Concurrent profile (PostgreSQL + Redis)

```bash
export TRINETRA_DATABASE_URL=postgresql://user@host/trinetra
export TRINETRA_REDIS_URL=redis://host:6379/0          # optional job hints; SQL stays authoritative
export TRINETRA_AUDIO_CACHE_URL=redis://host:6379/1    # required when running more than one API process
export TRINETRA_SERVER_SECRET=...                      # or share TRINETRA_DATA_DIR between processes
TRINETRA_WORKERS=0 uvicorn app.main:app --workers 2 --port 8000   # API processes (dispatcher only)
TRINETRA_WORKERS=2 python -m app.soc.worker                       # each worker process, repeat as needed
```

Migrate a quiesced SQLite database with `python backend/tools/migrate_sqlite_to_postgres.py data/trinetra.db $TRINETRA_DATABASE_URL`. It compares IDs, row counts, case states, event links and settlement totals. Rollback means pointing back at the untouched SQLite file. See `docs/operations.md`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TRINETRA_DATABASE_URL` | `sqlite:///backend/data/trinetra.db` | SQLite WAL or `postgresql://` |
| `TRINETRA_ANALYST_PASSCODE` | generated to `data/analyst-passcode.txt` | SOC sign-in |
| `TRINETRA_WORKERS` | 2 | In-process SOC worker threads (0 = API only) |
| `TRINETRA_SOC_TIER` | 0 | 0 = reports and proposals only; 1 = agent may apply guarded reversible actions |
| `TRINETRA_SOC_KILL_SWITCH` | 0 | 1 = refuse all agent-initiated actions |
| `TRINETRA_CAPTURE_FRESH_MS` | 600000 | Capture freshness window for submission |
| `TRINETRA_FRONTEND_DIST` | unset | Serve the built UI from the API |

## Tests

```bash
./scripts/test-all.sh                                   # everything below
cd backend && pytest -q                                 # unit, integration, concurrency on SQLite
TRINETRA_TEST_PG_URL=postgresql://... pytest -q         # adds live PostgreSQL for every DB test
cd frontend && npm test && npm run typecheck            # formatting/parsing unit tests, types
./scripts/e2e.sh                                        # real Chrome: fake-mic capture, denial, silence, SOC, axe
python backend/tools/loadtest.py --base ... --passcode ...   # latency, throughput, duplicate retries
```

The results for this build are in `docs/verification-report.md`.

## Gemini analyst workspace

Customer money requests are simulated incoming transfers from the saved contact into
the customer’s sandbox account. They use `POST /api/v2/payment-requests`.
Existing outgoing transfers and the original `POST /api/v2/payments` retain their direction.

The dashboard at `/analyst` reads existing sandbox cases and stores agent findings and
analyst reviews per case version. It uses LangChain prompts and a LangGraph workflow
with Triage, Investigator, Decision, Monitor, and Reporter stages. Reviews record a
disposition and note in the workspace. To verify an incoming request, a signed-in
analyst must have a completed analysis for the current case version. Verification
settles the transfer and updates the customer’s authenticated receipt. Old SOC
dashboard links open `/analyst`.

From the project root, using the project virtual environment:

```bash
source .venv/bin/activate
uv pip install -r backend/requirements-analyst.txt
read -rsp 'Workspace password: ' TRINETRA_ANALYST_WORKSPACE_PASSWORD
export TRINETRA_ANALYST_WORKSPACE_PASSWORD
printf '\n'
./scripts/start.sh
```

Open `http://127.0.0.1:8000/analyst` and sign in as `admin` with the workspace
password you entered. Export `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) in that same
shell to enable analysis. The default model is `gemini-3.5-flash-lite`, configurable
with `TRINETRA_ANALYST_MODEL`. Analysis normally makes five Gemini requests.
Each stage can retry once after a timeout, network error, or transient server
error within the overall 70-second analysis deadline.

For LangSmith, set `LANGSMITH_API_KEY` and `LANGSMITH_TRACING=true`.
`LANGSMITH_PROJECT` defaults to `trinetra-analyst`. Traces hide inputs, outputs,
and metadata. Gemini receives case facts such as the transfer amount and evidence
status. Customer names, account identifiers, remarks, and transcripts stay local.
