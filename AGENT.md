# AGENT INSTRUCTION & REPOSITORY CONTRACT: PROJECT TRINETRA

> Historical prototype reference. See [Figure 1](docs/agentic.pdf), [active phases](docs/plan.md) and [runtime](docs/runtime.md).

> **Audience:** Claude Code / AI Coding Agents / Developers working in this repository.  
> **Repository Root:** `/home/a9rmx_1990/hackathon/`  
> **Architecture Reference:** [`ARCHITECTURE.md`](file:///home/a9rmx_1990/hackathon/ARCHITECTURE.md)  
> **Status:** Backend Complete (52/52 Tests Passing) | Frontend In-Progress

---

## 1. Project Overview & Context

**TRINETRA** (*The Third Eye of Digital Trust*) is an in-line banking security middleware and Security Operations Center (SOC) dashboard. It intercepts Generative AI cyber fraud in **sub-150ms** before money leaves the bank.

### The 3 Core Threat Vectors Handled:
1. **AI Voice Clone Impersonation:** Neural vocoder artifacts in payment authorization phone calls.
2. **5-Hop Rapid Mule Rings:** High-velocity multi-hop fund dispersion across shell bank accounts.
3. **"Digital Arrest" Extortion:** Coercive social engineering impersonating law enforcement (CBI, Police) to liquidate savings into "safe government escrow" accounts.

---

## 2. Repository Layout & Existing Assets

```
/home/a9rmx_1990/hackathon/
├── ARCHITECTURE.md                 # Complete system design, math formulations, API schemas
├── AGENT.md                        # This agent guide (Single source of truth)
├── PLAN.md                         # Prototype milestone plan
├── docs/                           # LaTeX whitepapers & problem statement docs
└── backend/                        # FULLY FUNCTIONAL BACKEND (52/52 TESTS PASSING)
    ├── .venv/                      # Python 3.12 virtualenv (uv-managed)
    ├── requirements.txt            # Frozen dependencies (fastapi, uvicorn, networkx, numpy, scipy, pydantic, httpx, pytest)
    ├── run.sh                      # Shell script to start backend on http://0.0.0.0:8000
    ├── integration_test.py         # Full end-to-end integration test runner
    ├── app/
    │   ├── main.py                 # FastAPI application, routes, and WebSocket hub
    │   ├── config.py               # Weights (w_audio=0.45, w_graph=0.40, w_nlp=0.15) & thresholds
    │   ├── schemas.py              # Pydantic schemas (TransactionPayload, InterceptionResponse, etc.)
    │   ├── websocket_manager.py    # SOCConnectionManager for real-time WebSocket broadcast
    │   ├── engines/
    │   │   ├── audio_engine.py     # DSP voice clone detection (LFCC, Wiener flatness, HF >4kHz)
    │   │   ├── graph_engine.py     # NetworkX directed graph, cycle detection, V_disp, Cytoscape export
    │   │   ├── nlp_engine.py       # Compiled regex coercion taxonomy for Digital Arrest & legal cues
    │   │   └── policy_engine.py    # Composite risk calculation & dynamic decision gating (ALLOW, STEP_UP, HOLD)
    │   └── simulator/
    │       └── scenarios.py        # 4 canonical attack feeds with pre-rendered WAV audio buffers
    └── tests/
        ├── test_phase1.py          # Configuration invariants & schema boundary tests
        ├── test_phase2_audio.py    # Voice clone vs authentic audio discrimination & latency tests
        ├── test_phase3_graph.py    # 5-hop mule networks, cycle loops & velocity tests
        ├── test_phase4_policy.py   # NLP extortion matching, weighting formulas & policy gate tests
        └── test_phase5_api.py      # REST endpoints, WebSocket streaming & simulator integration tests
```

---

## 3. Verified Backend Execution Commands

The backend is fully operational. Always use these exact commands:

* **Activate Virtual Environment:**
  ```bash
  cd /home/a9rmx_1990/hackathon/backend
  source .venv/bin/activate
  ```
* **Run Entire Test Suite (52 Tests):**
  ```bash
  cd /home/a9rmx_1990/hackathon/backend
  PYTHONPATH=. .venv/bin/pytest -v tests/
  ```
* **Run End-to-End Integration Test:**
  ```bash
  cd /home/a9rmx_1990/hackathon/backend
  PYTHONPATH=. .venv/bin/python integration_test.py
  ```
* **Start Live Backend Server (Port 8000):**
  ```bash
  /home/a9rmx_1990/hackathon/backend/run.sh
  # Runs on: http://0.0.0.0:8000
  # Interactive Docs: http://localhost:8000/docs
  # WebSocket Feed: ws://localhost:8000/ws/soc-stream
  ```

---

## 4. Exact API Contracts (DO NOT MOCK - USE LIVE ENDPOINTS)

The frontend must communicate directly with the live backend running on `http://localhost:8000` and `ws://localhost:8000`:

1. **`GET /health`:** Check backend status and active WebSocket clients count.
2. **`GET /api/v1/metrics`:** Returns `{total_evaluated, allowed, stepped_up, held, average_latency_ms, quarantined_accounts_count}`.
3. **`GET /api/v1/scenarios`:** Returns metadata for the 4 preset attack scenarios.
4. **`POST /api/v1/scenarios/trigger/{scenario_id}`:** Triggers one of the 4 demo scenarios:
   * `SCENARIO_1_BASELINE` (Clean Payment $\rightarrow$ `ALLOW`)
   * `SCENARIO_2_VOICE_CLONE` (CEO Voice Clone $\rightarrow$ `HOLD`)
   * `SCENARIO_3_MULE_RING` (5-Hop Mule Ring $\rightarrow$ `HOLD`)
   * `SCENARIO_4_DIGITAL_ARREST` (Digital Arrest Extortion $\rightarrow$ `HOLD`)
5. **`POST /api/v1/intercept`:** The live in-line transaction evaluation gateway. Accepts `TransactionPayload`, returns `InterceptionResponse` in $< 2.5$ ms.
6. **`GET /api/v1/graph/mule-network?focus_account={id}`:** Returns Cytoscape.js format `{nodes: [...], edges: [...]}`.
7. **`POST /api/v1/soc/override`:** Analyst action `{account: string, action: "CONFIRM_FREEZE" | "RELEASE_HOLD", analyst_id: string}`.
8. **`WS /ws/soc-stream`:** Real-time bi-directional WebSocket connection. Automatically broadcasts `TRANSACTION_EVALUATED` and `ANALYST_OVERRIDE` events containing full transaction breakdowns, acoustic diagnostics, and Cytoscape subgraphs.

---

## 5. Next Task: Frontend Implementation Specification

The frontend must be created in `/home/a9rmx_1990/hackathon/frontend` using **Vite + React (TypeScript) + Tailwind CSS + Lucide Icons + Cytoscape.js**.

### Crucial Feature Requirement: Dual-Perspective UI
The frontend must provide a toggleable or tabbed view allowing judges to experience both sides of the cybersecurity equation:

#### Perspective A: "Retail Banking Voice Gateway" (The Customer View)
* A modern consumer/enterprise banking transfer form:
  * Fields: Sender Account, Recipient Account, Amount (INR), Payment Channel (UPI, IMPS, WIRE).
  * Narrative Context / Remark: Text box for payment remarks.
  * Voice Authorization Module:
    * Microphone recording button (uses browser Web Audio API to record audio, convert to Base64 WAV).
    * Quick-Test Buttons: "Load Authentic Voice Sample" vs. "Load Cloned Voice Sample" (for quick live judging).
  * "Authorize Payment" Button: Submits to `POST /api/v1/intercept`.
  * Visual Outcome: Immediate customer feedback:
    * Clean $\rightarrow$ "Payment Successfully Dispatched" (Green).
    * Held $\rightarrow$ "Transaction Intercepted & Frozen! Deepfake voice or mule activity detected" (Red banner).

#### Perspective B: "Enterprise SOC Command Console" (The Bank Security View)
* Real-time live threat monitoring console:
  * **Top Metrics Bar:** Real-time counters from `GET /api/v1/metrics` and SLA latency stopwatch.
  * **1-Click Attack Simulator Bar:** Buttons to trigger the 4 preset scenarios on demand.
  * **Live Stream Queue:** Real-time scrolling table of transactions received from `ws://localhost:8000/ws/soc-stream`.
  * **Interactive Cytoscape.js Visualizer:** Renders the transaction topology. Mule ring accounts flash in glowing red; normal accounts in blue. Clicking a node displays balance and hop count.
  * **Audio Spectrogram & Vocoder Inspector:** Visualizes the acoustic frequencies of authorization calls, highlighting the $> 4\text{ kHz}$ neural vocoder anomaly band and Wiener spectral flatness meter.
  * **Analyst Action Drawer:** Human-in-the-loop controls: `[Confirm Freeze]` or `[Release Hold]` calling `POST /api/v1/soc/override`.

---

## 6. Coding Standards & Ground Rules for the Agent

1. **Ponytail Standard (Zero Slop / Minimal Complete Code):**
   * Do not write redundant abstractions, fake mock engines, or speculative code nobody asked for.
   * Write clean, idiomatic, fully-functional TypeScript and React components.
2. **Real Endpoints Only:**
   * Never hardcode dummy random values in the frontend when the backend already computes the real mathematical DSP and Graph metrics. Always connect to the backend WebSocket and REST endpoints.
3. **No Heavy External ML Dependencies Needed:**
   * The backend does NOT need PyTorch weights or HuggingFace model downloads. All DSP and Graph analysis runs deterministically and instantly in pure NumPy, SciPy, and NetworkX.
4. **Resilience & Error Handling:**
   * Handle WebSocket reconnects gracefully with visual status badges (Green = Live WS Connected, Red = Reconnecting).
