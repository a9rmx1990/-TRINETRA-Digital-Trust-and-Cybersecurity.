# TRINETRA: prototype to `architecture.png`

> Historical prototype reference. See [Figure 1](docs/agentic.pdf), [active phases](docs/plan.md) and [runtime](docs/runtime.md).

## Target and starting point

The image specifies this path: caller web app (WebRTC microphone and payment form) → FastAPI ingestion gateway (aiortc and voice activity detection) → voice deepfake model, speech to text, coercion text model, and mule graph model → learned risk fusion with hard overrides → payment gate and AI SOC console. Speech to text feeds the coercion model; the graph also receives payment and account history. Purple boxes in the image are **model backed components**, not the current rule based approximations.

The repository already has a React payment form and microphone widget, a FastAPI `POST /api/v1/intercept`, DSP audio scoring, regex coercion scoring, a NetworkX graph, fixed weighted policy, a WebSocket SOC feed, four scenarios, and manual account quarantine. Preserve these as a working reference path and demo fixtures while adding the new capabilities.

| Target component | Current implementation | Required change |
| --- | --- | --- |
| Caller WebRTC app | `frontend/src/components/VoiceAuthWidget.tsx` records a 3 second WebM clip and posts base64 in transfer JSON | Establish an audio session, stream microphone audio, show capture/consent and session status; bind its session ID to the payment |
| Ingestion gateway | `backend/app/main.py` accepts a single JSON request; `audio_engine.py` decodes the whole clip | Add WebRTC signaling and aiortc receiver, VAD, bounded audio windows, format normalization, session timeout, and correlation IDs |
| Voice deepfake | `backend/app/engines/audio_engine.py` uses spectral thresholds on generated sample audio | Serve a calibrated wav2vec2 or WavLM classifier with score, model version, quality flags, and an unavailable state |
| Speech to text | No ASR; `narrative_context` is typed by the payer | Stream or incrementally transcribe with Whisper, identify English/Hindi/Kannada, carry timestamps and language to coercion analysis |
| Coercion text | `backend/app/engines/nlp_engine.py` uses English regex | Add fine tuned XLM-R classifier plus a zero shot path for low data labels; merge call transcript and typed text with provenance |
| Mule graph | `backend/app/engines/graph_engine.py` is a process local `DiGraph` with rules | Store transaction edges and account features durably, score an event-time 5 hop neighborhood with NetworkX features plus a trained GNN |
| Risk fusion | `backend/app/engines/policy_engine.py` uses fixed weights and thresholds | Train and calibrate fusion on out-of-fold modality scores; retain explicit quarantine and severe threat overrides, and define missing-signal behavior |
| Payment gate | `/intercept` returns a decision; no payment system is called | Add a payment adapter and transaction state machine that actually blocks settlement on HOLD and requires a completed challenge on STEP_UP |
| AI SOC | `SOCConsole.tsx` displays events, graph, diagnostics, and a manual account override | Persist cases and evidence; add a read-only case copilot with cited evidence, summaries, and suggested triage actions |

## Implementation sequence

### 0. Lock the contracts and measure the baseline

- Define `call_session_id`, `transaction_id`, `account_id`, event time, model versions, modality status (`ready`, `missing`, `invalid`, `timeout`), scores, evidence references, and payment state. Version REST/WebSocket payloads and preserve the current `/api/v1/intercept` contract as a compatibility route during migration.
- Add a small labeled evaluation set covering real human speech, cloned speech from several generators, English/Hindi/Kannada coercion and benign calls, mule and legitimate 5 hop patterns. Split by speaker, generator, account group, and time to avoid leakage. The existing generated sine wave scenarios are useful for regression only; they cannot validate real-world detection accuracy.
- Benchmark latency as separate **call preparation** and **payment authorization** stages. A 150 ms payment decision is plausible only when audio/ASR/model signals are already computed during the call. Record p50/p95/p99 end-to-end timing and missing-modality rates before setting the gate SLA.
- Exit: written API/event schemas, a reproducible baseline report, and a fixed evaluation dataset.

### 1. Build live call ingestion

- Extend `VoiceAuthWidget.tsx` and `TransferForm.tsx`: create a call session, connect a WebRTC peer, stream microphone audio, and submit only the session ID with the payment. Include teardown, retry, permission denial, and stale-session handling. Keep clip upload as a development fallback.
- Add FastAPI signaling endpoints and an `aiortc` peer handler. Run VAD on normalized 16 kHz mono frames, emit bounded voiced segments to an inference queue, and store only short lived encrypted evidence when retention is enabled. Set limits on concurrent sessions, duration, payload size, and queue depth.
- Exit: browser audio reaches the server while the payment form remains usable, and a payment is correlated to exactly one authenticated call session.

### 2. Replace rule proxies with model services

- Voice: wrap a fine tuned wav2vec2/WavLM binary classifier behind a stable `score_audio(window) -> score, quality, evidence, version` interface. Evaluate on unseen speakers, languages, codecs, noise, and clone generators; calibrate probability and define minimum voiced duration. Retain DSP features as auxiliary evidence, not as a claim of model accuracy.
- ASR: run Whisper on VAD speech windows, preserve timestamps and language confidence, and combine partials into a transcript. Verify English, Hindi, and Kannada with human reviewed word error rate and domain terminology.
- Coercion: use XLM-R for multilingual classification with separate labels for authority impersonation, transfer demand, urgency, and benign discussion. Apply a zero shot model only where labeled data is sparse, with its own threshold and evaluation. The coercion model consumes ASR text plus typed narrative with source tags.
- Give each model a timeout, version, health check, and `unavailable` result. Never convert model failure into a clean zero score. Preload models and benchmark CPU/GPU memory and throughput before choosing shared process versus separate inference workers.
- Exit: each model meets a documented validation threshold on held-out data and returns a typed result under its latency budget.

### 3. Make mule scoring event based and durable

- Persist accounts, transactions, payment status, quarantine status, and event times in a database. Keep a bounded recent graph cache for fast neighborhood extraction; rebuild it from storage on restart. Replace `DiGraph` if repeated transfers between the same pair matter, since current edges overwrite each other.
- Score the **proposed** transfer against prior committed or observed transfers without counting a rejected payment as completed money movement. Use 5 hop features including age, velocity, fan-out, cycles, shared device/beneficiary where available, and edge recency. Train a GNN on labeled temporal graph snapshots, calibrate it, and compare it with the existing rules on false positives and missed mule rings.
- Exit: restart and concurrent-worker tests give the same result, replayed or duplicate transaction IDs are idempotent, and known mule chains remain detectable.

### 4. Add risk fusion and the actual payment gate

- Train fusion on out-of-fold voice, coercion, and graph scores; include signal quality, missingness, and account context. Calibrate the final risk score and choose ALLOW/STEP_UP/HOLD thresholds from measured cost and false-positive targets. Keep versioned hard overrides for quarantined accounts and validated severe signals. Do not let a SOC copilot change these rules.
- Implement states such as `PENDING_RISK → ALLOWED → SETTLED`, `PENDING_RISK → STEP_UP → VERIFIED → ALLOWED`, and `PENDING_RISK → HELD → RELEASED/CANCELLED`. The payment adapter alone may authorize settlement; the browser's success banner must reflect the adapter's result, not only a risk decision. Use transaction ID idempotency, atomic state changes, and an audit record for overrides.
- Define timeout behavior with the bank: for high risk or missing critical signals, hold or request step-up; for lower risk, use a documented fallback policy. Test that service failure cannot silently settle a held payment.
- Exit: integration tests prove HOLD never calls settlement, STEP_UP cannot settle before verification, ALLOW calls the adapter once, and retries cannot double settle.

### 5. Build case driven SOC assistance

- Persist an incident case per held or stepped-up payment with evidence links, transcript excerpts, scores, graph snapshot, model versions, and action history. Stream case updates over the existing WebSocket; add reconnect catch-up through a paginated cases API.
- Extend `SOCConsole.tsx` and `EventDetailDrawer.tsx` with case status, assigned analyst, timeline, evidence, and explicit payment release/freeze controls. The current account-only override needs transaction-level authorization and audit fields.
- Add an AI copilot that retrieves **only case evidence**, summarizes why a case was flagged, cites the exact transcript span/graph path/score, and suggests questions or next steps. Keep it advisory with analyst approval for actions, redact sensitive fields from prompts, and record prompts, outputs, and feedback for review.
- Replace the current randomized canvas bars in `SpectrogramPanel.tsx` with actual server-provided time-frequency data or label the panel as a score summary.
- Exit: an analyst can open a case after reconnect, inspect evidence, understand the suggested action, and complete an audited intervention.

### 6. Roll out by evidence

- Run the new models in shadow mode beside the existing rules, compare decisions and latency on the same traffic, and review false holds before switching the gate. First enable model recommendations in SOC, then controlled payment gating behind a feature flag.
- Add privacy and operational controls: authenticated customer/analyst roles, TLS/WebRTC transport security, scoped CORS, encryption and retention for audio/transcripts, model artifact pinning, metrics/traces, alerting, and rollback to the known fallback policy.
- Gate release on held-out model results, multilingual review, payment state-machine tests, load tests at target concurrency, p95/p99 authorization latency, and a complete four-scenario demo using the new session path.

## Key design decisions to resolve before model training

1. **Payment integration:** which sandbox/rail owns authorize, settle, hold, and release? Without an adapter, the current UI can demonstrate decisions but cannot prove pre-settlement interception.
2. **Audio evidence:** consent text, retention period, and whether raw audio may be stored. This determines the case evidence design.
3. **Training data:** access to licensed multilingual calls, real spoof samples, labeled mule histories, and negative examples. Model claims depend on these datasets.
4. **Deployment budget:** CPU/GPU availability and expected concurrent calls. This determines model size, serving layout, and whether the 150 ms payment gate target is feasible after precomputation.

## Suggested delivery slices

1. **Integrated vertical slice:** WebRTC + VAD + session correlation + existing scorers + a sandbox payment gate. This makes the diagram's end-to-end path real before model replacement.
2. **Model slice:** voice, ASR, coercion, and graph models with validation and shadow scoring.
3. **Decision and operations slice:** learned fusion, durable cases, copilot, analyst workflow, and staged gate rollout.

Avoid treating the existing `<150 ms` engine timing as proof for the target architecture: current tests measure short in-process rule calls and generated fixtures, while live ASR, model inference, network transport, and payment authorization have different costs.
