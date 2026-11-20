# Running TRINETRA

TRINETRA v2 is a local banking sandbox. It can settle a synthetic transfer into its SQLite ledger. The default caller account and recipients are fixtures. The browser generates a random bearer credential for ownership within that sandbox. A production identity provider, actual funding accounts and a bank adapter are outside the local runtime.

## Start the sandbox

Use Python 3.12 and Node 24. The existing workspace has dependencies available. For a fresh checkout, create a virtual environment in backend and install backend/requirements.txt, then run npm ci in frontend.

In one terminal from the root:

```bash
bash backend/run.sh
```

In another terminal:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1
```

Open http://localhost:3000, review the microphone consent, and start a voice session. End the session to open the transfer form. Submit the payment and open **Analyst console** with the analyst key from the root .env to review flagged transfers. For step-up, issue a short-lived verification code in the case and enter it on the payment status page. Test fixture routes in v2 require TRINETRA_ENABLE_FIXTURES=1 and have no portal controls.

Set TRINETRA_DB to select a separate SQLite file for a fresh run. The default is backend/data/sandbox.sqlite3. State transitions, settlement entries, cases, events and outbox records commit in ledger transactions. The sandbox ledger acts as the payment rail. The SOC worker consumes cases after commit, and the case stream replays cursor-based update notices.

## WebRTC and Redis

Install backend/requirements-live.txt in the backend virtual environment and restart. The caller detects aiortc and negotiates a WebRTC audio peer. If aiortc is absent, the caller streams 16 kHz mono PCM over HTTP using AudioWorklet. Browser microphone access requires localhost or HTTPS. Configure TRINETRA_ICE_SERVERS as a JSON array of ICE server objects for non-local networks. Keep real deployments behind a trusted origin and use short-lived TURN credentials. Set TRINETRA_REDIS_URL to mirror short-lived scoring snapshots in Redis. Media capture remains single-process. Raw PCM is kept only in capped rolling memory until session completion or expiry.

## Model artifacts

Install backend/requirements-models.txt. Copy backend/models.example.json to a local manifest and point TRINETRA_MODELS at it. Use trusted local artifacts. Remove entries for models you are not evaluating. Ensure Whisper is a CTranslate2 model directory. The spoof positive index and coercion labels must match the trained heads. Zero-shot fallback runs only for languages explicitly allowed in its entry. Models load on demand and emit a status and version. The live gate uses learned risk signals. It uses a version-matched fusion artifact when installed and otherwise uses the strongest eligible learned score. Add a fusion artifact only after evaluating the intended bundle. Policy sandbox-models-v3 excludes an inconclusive voice score from fusion and automatic risk scoring. The analyst retains the original score. Missing or inconclusive required evidence forces at least step-up. DSP and NetworkX heuristics remain as analyst evidence and for explicit fixtures. Per-model hard overrides can be configured with a reviewed_hold_threshold on a 0–100 scale.

All commands below run from backend with PYTHONPATH=. and its virtual environment active.

| Trainer | Reviewed JSONL inputs | Artifact |
|---|---|---|
| python tools/train_detector.py audio BASE TRAIN TEST OUTPUT --labels genuine spoof | id, relative audio WAV path, labels list containing one class | Transformers classifier and held-out counts |
| python tools/train_detector.py text BASE TRAIN TEST OUTPUT --labels benign authority escrow urgency | id, text, labels list | Transformers classifier and held-out counts |
| python tools/train_graph.py TRAIN TEST OUTPUT | id, binary label, features and directed edges. Feature order is log in-degree, log out-degree, normalized recipient age, recipient flag. Recipient is row zero. | TorchScript model and held-out Brier score |
| python tools/train_fusion.py TRAIN CALIBRATION TEST OUTPUT --model-versions VOICE TEXT GRAPH | id, binary label, voice/text/graph scores in 0–100 or null. Use detector predictions from disjoint folds. Use a hyphen version for an absent detector. | JSON weights, calibration and held-out report |

The sample manifest names paths for locally trained or approved artifacts. It contains no pretrained project weights. The trainers check IDs within and between splits. Dataset owners still need to group by speaker, generator, account and time before training. The basic reports support initial development. Use the model handbook for release evaluation, including subgroup and operating-threshold checks. [Model engineering](models.md)

## Agentic SOC

The default sandbox runs the SOC worker inside FastAPI on SQLite. Each flagged payment and relevant case update creates a durable outbox job. The worker runs Triage, Investigator, Decision, Monitor and Reporter stages. The analyst console shows case evidence, verdicts, agent timeline, action proposals, 30-day watches, and adjudication. The dashboard refreshes by committed event cursor.

The investigator builds an evidence report locally. Optionally set TRINETRA_LOCAL_LLM_PORT and TRINETRA_LOCAL_LLM_MODEL for a self-hosted model on 127.0.0.1 with a compatible chat completions interface. The client uses no API key. Automatic local enrichment uses TRINETRA_COPILOT_AUTO. Transcript excerpts require TRINETRA_COPILOT_TRANSCRIPT=1. The monitor schedules daily forward checks for 30 days.

| Setting | Behavior |
|---|---|
| TRINETRA_AGENT_MAX_TIER | Defaults to 0. Tier 1 permits guarded reversible actions. Tier 2 permits analyst approval of high-impact proposals. |
| TRINETRA_AGENT_AUTO_CLOSE | Optional sampled benign closure for independently verified, low-risk settled cases. Defaults to 0. |
| TRINETRA_AGENT_ENGINE | Local state machine by default. Set langgraph after installing requirements-agentic.txt. |
| TRINETRA_SOC_INLINE | Defaults to 1. Set 0 when running a dedicated worker. |
| TRINETRA_DATABASE_URL | Optional Postgres URL. Without it, TRINETRA_DB selects the SQLite ledger. |
| TRINETRA_SOC_REDIS_URL | Optional Redis Streams URL for committed SOC job IDs. TRINETRA_REDIS_URL independently configures the audio evidence cache. |

From backend with PYTHONPATH=. and the same environment as FastAPI, use the following commands.

~~~bash
.venv/bin/python -m app.live.soc_worker
.venv/bin/python -m app.live.soc_mcp CASE_ID --service evidence
.venv/bin/python tools/migrate_soc_postgres.py data/sandbox.sqlite3
~~~

Use the worker command with TRINETRA_SOC_INLINE=0. The read-only MCP server speaks stdio and is scoped to the selected case. Add --fastmcp after installing requirements-agentic.txt to use the FastMCP transport adapter. Quiesce the SQLite ledger and provide an empty Postgres target for migration. See [Operations](operations.md).

The analyst-scoped /api/v2/soc/analytics and /api/v2/soc/evaluation endpoints expose structured metrics and adjudicated examples. Reports and notifications are local records. Optional benign closure samples 10% of eligible cases for analyst QA. The sandbox records an approved investigation report for analyst handoff.

## Verification

The [harness](harness.md) lists unit, in-process integration, frontend, and service checks. [Traceability](traceability.md) records what each Figure 1 component implements and what needs environment-specific validation.

## Voice-first portal setup

Copy .env.example to .env, fill in the backend values, and restart the backend. The launcher loads .env automatically.

```bash
cp .env.example .env
# Fill in TRINETRA_ANALYST_KEY and any model or provider configuration in .env.
bash backend/run.sh
```

A local spoof classification checkpoint (wav2vec2 or WavLM) plus its reviewed genuine and hold cutoffs is needed for likely genuine or suspected synthetic results. Enter numeric values on the 0–100 scale for reviewed_genuine_threshold and reviewed_hold_threshold in the spoof manifest entry. Missing scores, unavailable checkpoints and scores between those cutoffs are inconclusive. Inconclusive voice sessions require additional verification unless another risk signal requires a hold. Local inference requires no API key. Whisper CTranslate2 and a trained XLM-R classifier add transcript and coercion evidence. The optional NLI, graph and fusion artifacts are described above.

No telephony or contact-center service is linked. The voice session captures browser microphone audio for screening. Confirmed settlement is inside the sandbox ledger.

### Replacing fixture scores with models

The backend executes Whisper and WavLM concurrently on usable audio windows. Whisper output goes to the same XLM-R classifier as typed remarks, with separate source evidence. Payment submission scores remarks and the recipient graph in parallel. The gate checks the GNN snapshot against current ledger edges before using it. Audio, text and graph scores are saved separately for the analyst.

Install the runtime with `backend/.venv/bin/python -m pip install -r backend/requirements-models.txt` if pip is installed in the environment, or `uv pip install --python backend/.venv/bin/python -r backend/requirements-models.txt`. The existing local environment points the ASR manifest entry to the cached Systran Whisper Base CTranslate2 checkpoint. The example manifest shows the other required paths. Start with WavLM Base+ fine-tuned for spoof classification and XLM-R Base fine-tuned on fraud or coercion labels. The base checkpoints by themselves have no task-specific classifier. Train the directed GNN using labeled, time-split recipient neighborhoods, and export its TorchScript artifact using the command above. Add the reviewed artifacts and thresholds to the local manifest and restart the backend. No hosted API key is required for these local models.

### Train a GNN from IBM AMLWorld data

The converter accepts a local IBM AMLWorld transaction CSV or a complete ZIP. The default ZIP member is `HI-Small_Trans.csv`. Use `--member HI-Large_Trans.csv` to select the large split.

```bash
cd backend
PYTHONPATH=. .venv/bin/python tools/prepare_aml_graphs.py data/archive.zip data/aml-graph
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. .venv/bin/python tools/train_graph.py \
  data/aml-graph/train.jsonl data/aml-graph/test.jsonl data/graph.pt --epochs 8
```

The converter uses the same bounded recipient graphs as the backend. History comes from the preceding 24 hours and excludes all transfers with the candidate's timestamp or later. It separates the time periods before sampling each label. The CSV has no account creation dates, so the converter uses the mature-account default for age. Evaluation is on class-enriched synthetic AML data. Its metrics cannot be interpreted as accuracy on live bank transfers or used to calibrate payment holds directly.

The current local manifest selects the GNN trained from the complete `HI-Small_Trans.csv` archive member. Its dataset split, weights and evaluation report live under `backend/data/aml-graph-hi-small/`. The earlier prefix model and its report are still in `backend/data/graph.pt` and `backend/data/aml-graph/`. The new model is configured with `review_only: true`. It provides evidence to the SOC, and the live gate requires verification if it has no validated graph score.
