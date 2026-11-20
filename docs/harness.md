# Verification harness

Run the fast tests before the integration checks. Use a temporary ledger and a fixture or stub provider. Record pass, failure, skip, and environment-specific checks.

| Check | Command |
|---|---|
| Unit and baseline contracts | From backend, run PYTHONPATH=. .venv/bin/pytest -q tests/test_soc_units.py tests/test_phase1.py tests/test_phase2_audio.py tests/test_phase3_graph.py tests/test_phase4_policy.py |
| In-process integration | From backend, run PYTHONPATH=. .venv/bin/pytest -q tests/test_soc_integration.py tests/test_sandbox_flow.py tests/test_phase5_api.py |
| Legacy demonstration | From backend, run PYTHONPATH=. .venv/bin/python integration_test.py |
| Frontend | From frontend, run npm test and npm run build |
| Service integration | Install requirements-agentic.txt, set TRINETRA_TEST_POSTGRES_URL and TRINETRA_TEST_REDIS_URL for isolated services, then run tests/test_soc_integration.py |
| Live browser | Start both servers on a network-capable host. Verify microphone permissions, WebRTC, a flagged transfer, the live timeline and analyst approval. |

| Phase | Unit checks | Integration checks |
|---|---|---|
| A0 | Model missingness, graph bounds, policy transitions | PCM correlation, duplicate submissions, sandbox fixtures, step-up and blocks |
| A1 | Bounded retry timing | Rollback, lease expiry, stale worker fencing, idempotent delivery |
| A2 | Scoped MCP schemas, transcript filter, graph hops and citation validation | MCP stdio, provider tool round trip and denial, report persistence |
| A3 | Tier, confidence, risk and state eligibility | Automatic step-up, hourly cap, kill switch, approval, rejection and reversible hold |
| A4 | Watch horizon and case similarity | Durable watch restart, case reopening, adjudication and analytics |
| A5 | Postgres parameter and JSON translation | Redis message duplicates with a transport double. Optional live Redis, Postgres, LangGraph and FastMCP checks require their dependencies. |
| A6 | Frontend test | Backend case WebSocket, build and live browser rehearsal where sockets are available |

Before activating models or automation beyond the sandbox, evaluate on labeled cases, check outcome calibration and override rates, and rehearse outbox recovery and payment idempotency. Report browser, external provider, production settlement and load evidence separately. [Runtime](runtime.md)

## Verification record

The latest local run passed 63 unit and baseline contract checks, followed by 25 in-process integration checks. The standalone legacy integration runner, frontend tests and production build also passed. Four optional checks were skipped for Postgres, Redis Streams, LangGraph and FastMCP. This workspace blocks socket binding and package downloads. The live browser, WebRTC and hosted provider were outside the verified environment. The TikZ source passed static structure checks.

### Follow-up verification on 2026-11-20

The rerun used Python 3.12.14 in `backend/.venv` and reproduced the counts above. Both frontend test files and the production build passed. The sandbox API test exercised analyst issuance, rejection of an incorrect code, and settlement after the owner submitted the correct code.

Local Whisper, spoof and coercion inference ran on CPU with the installed artifacts. Whisper transcribed a synthesized English grocery-payment sentence. The spoof classifier assigned that synthesized clip a score of 0.09 out of 100. This single example supports keeping the voice decision thresholds unset pending representative labeled evaluation.

Replaying the exported GNN on all 3,600 held-out synthetic AML graphs reproduced a Brier score of 0.09684. At a 0.5 threshold it identified 48 of 400 positives and flagged 55 of 3,200 negatives. The graph artifact remains configured for analyst review. Production calibration and analyst override rates require representative labeled cases and adjudications.

The hosted endpoint, model and key settings were populated. DNS resolution failed before authentication could be tested. Installation of the optional agentic and WebRTC dependencies also failed at DNS resolution. Loopback socket creation and Docker access were denied. Live checks require a socket-enabled host with package access, isolated Postgres and Redis services, and a browser with microphone access.

### Local audio and text classification evaluation

Run `backend/tools/run_classification_evaluation.sh text` or `backend/tools/run_classification_evaluation.sh audio` from the root. The launcher uses the installed artifacts in TRINETRA_MODELS. Text compares 16 labeled messages at 69/100. Audio compares 12 generated clips at 50/100 and requires espeak-ng, flite and ffmpeg. This measures synthetic detection only. The evaluation cutoffs do not configure payment decisions.


The audio check compares one- and two-second windows and both binary class mappings. The transcript check runs the full reference utterance through Whisper and compares its downstream risk label with the label from the reference text. Use `backend/tools/run_classification_evaluation.sh transcript` for the built-in synthetic examples. Supply `--cases path/to/evaluation.jsonl` to any mode to evaluate other examples. Audio files are resolved relative to the JSONL file. A paired example has the following format.

```json
{"audio":"calls/001.wav","voice_label":"real","language":"hi","text":"यह नवंबर महीने का किराया है।","expected":"benign"}
```

On 12 generated English clips, class 0 as fake detected 2 at one second and 1 at two seconds. Class 1 as fake detected 10 and 11 respectively. Genuine caller false alarms remain unmeasured. Both reference text and full-utterance Whisper transcripts detected 4 of 6 risky clips and classified all 6 benign clips correctly. The two misses were two renderings of the same extortion message. These measurements cover six distinct utterances.

On the 16 typed examples, a temporary sandbox ledger with no voice session requested verification on all 8 benign transfers and on 4 risky transfers. It held the remaining 4 risky transfers. On the later half of the existing time-split synthetic AML test set, the graph model at 0.5 detected 43 of 299 positives and flagged 34 of 1,501 negatives. It remains review-only.
