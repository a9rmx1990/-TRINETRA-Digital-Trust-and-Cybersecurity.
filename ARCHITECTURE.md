# TRINETRA: Architecture & Technical Specification

> Historical prototype reference. See [Figure 1](docs/agentic.pdf), [active phases](docs/plan.md) and [runtime](docs/runtime.md).

> **Project Name:** TRINETRA (The Third Eye of Digital Trust)  
> **Track:** Digital Trust and Cybersecurity  
> **Status:** Backend Complete (52/52 Unit Tests Passing, < 1.5ms Latency) | Frontend In-Progress  
> **Core Mission:** Shift banking fraud defense from reactive post-incident reporting to real-time pre-settlement active interception (< 150ms).

---

## 1. Problem Formulation & The 3 Threat Vectors

Generative AI in 2025–2026 has rendered legacy relational anti-fraud engines (FICO Falcon, static AML rules) obsolete because victims authorize illicit transfers themselves using authentic credentials under machine-generated coercion:

1. **AI Voice Clone Impersonation:** Scammers harvest <5 seconds of audio to synthesize neural vocoders (HiFi-GAN, WaveGlow, Diffusion) impersonating executives (CEO fraud) or family members to authorize high-value out-of-band wire payments.
2. **"Digital Arrest" & Psychological Extortion:** Algorithmic social engineering presenting fake law enforcement credentials (CBI, Cyber Police, Customs, Supreme Court) coercing victims into liquidating savings into "safe state escrow" accounts.
3. **5-Hop Rapid Mule Rings:** Syndicated networks dispersing stolen funds across 5–10 hops of newly provisioned or dormant shell bank accounts in under 45 seconds before post-settlement freezing can take effect.

---

## 2. End-to-End System Topology

```
                   ┌──────────────────────────────────────────────┐
                   │    INCOMING TRANSACTION TELEMETRY INGESTION  │
                   │  - Transaction Payload (UPI / IMPS / WIRE)   │
                   │  - Audio Stream / Call (Base64 WAV / PCM)    │
                   │  - Context Remarks / Extortion Script Text   │
                   └──────────────────────┬───────────────────────┘
                                          │
       ┌──────────────────────────────────┼──────────────────────────────────┐
       ▼                                  ▼                                  ▼
┌─────────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│   Acoustic Forensics    │    │   Graph Intelligence    │    │  Coercive Context NLP   │
│   (audio_engine.py)     │    │   (graph_engine.py)     │    │     (nlp_engine.py)     │
│ - LFCC High-Freq Bands  │    │ - Directed Multigraph   │    │ - Authority Impersonate │
│ - Wiener Flatness (SFM) │    │ - 5-Hop Chain Traversal │    │ - Safe Escrow Patterns  │
│ - 4kHz-8kHz HF Leakage  │    │ - Cycle Detection (DFS) │    │ - Coercive Urgency Cues │
│ - Spectral Roll-off     │    │ - Velocity Ratio V_disp │    │ - Synergy Multiplier    │
└────────────┬────────────┘    └────────────┬────────────┘    └────────────┬────────────┘
             │                              │                              │
             └──────────────────────┬───────┴──────────────────────────────┘
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │         Unified Risk Aggregator & Policy Engine         │
       │                   (policy_engine.py)                    │
       │    R(T) = 100 * (0.45*S_audio + 0.40*S_graph + 0.15*S_nlp)   │
       │    Emergency Overrides: Voice Clone >= 85 | Mule >= 85   │
       └────────────────────────────┬────────────────────────────┘
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
┌──────────────────────────────────┐ ┌──────────────────────────────────┐
│   DYNAMIC ACTION GATING          │ │   REAL-TIME SOC STREAM (WS)      │
│ • ALLOW   (< 35.0): Fast-path    │ │ • ws://localhost:8000/ws/soc-st  │
│ • STEP_UP (35.0 - 69.9): Friction│ │ • Broadcasts Cytoscape Subgraph  │
│ • HOLD    (>= 70.0): Intercept   │ │ • Audio Spectrogram Diagnostics  │
│   + Auto-Quarantine Target Node  │ │ • Component Breakdown Metrics    │
└──────────────────────────────────┘ └──────────────────────────────────┘
```

---

## 3. Core Engine Mathematical Formulations

### 3.1 Acoustic Forensics Engine (`audio_engine.py`)
Analyzes raw audio (16kHz WAV / PCM) in **1.22 ms** without requiring heavy pre-trained neural networks:
* **Wiener Spectral Flatness Measure ($SFM$):**
  $$SFM = \frac{\exp\left(\frac{1}{N}\sum_{k=0}^{N-1} \ln(S(k) + \epsilon)\right)}{\frac{1}{N}\sum_{k=0}^{N-1} S(k) + \epsilon}$$
  Voiced biological speech exhibits sharp formant resonances ($SFM \approx 0.00 - 0.02$). Neural vocoders leave flat high-frequency floor noise ($SFM > 0.03 \rightarrow +35\text{ pts}$).
* **High-Frequency Energy Persistence ($HF_{\text{ratio}}$):**
  $$HF_{\text{ratio}} = \frac{\sum_{f \ge 4000\text{Hz}} |X(f)|^2}{\sum_{f} |X(f)|^2 + \epsilon}$$
  Human voice drops sharply above 3.5 kHz. Neural vocoders exhibit abnormal power leakage $> 4\text{ kHz}$ ($HF_{\text{ratio}} > 0.18 \rightarrow +35\text{ pts}$).
* **Spectral Roll-Off:** Frequency below which $85\%$ of spectral energy resides. Vocoder speech pushes $> 4000\text{ Hz}$ ($+20\text{ pts}$).

### 3.2 Graph Intelligence Engine (`graph_engine.py`)
Maintains an in-memory directed multigraph `networkx.DiGraph` evaluating topology in **0.08 ms**:
* **Outflow Dispersion Velocity Ratio ($V_{\text{disp}}$):**
  $$V_{\text{disp}} = \frac{\sum \text{Outflow}}{\sum \text{Inflow} + \epsilon} \cdot \frac{1}{\Delta t_{\text{hours}} + 0.005}$$
  Detects accounts dumping received deposits into downstream accounts within seconds ($V_{\text{disp}} > 1.5 \rightarrow +30\text{ pts}$).
* **$k$-Hop Downstream Path Search ($k \le 5$):**
  Traverses sequential child transfers. 4+ sequential hops in short intervals flags syndicated mule layering ($+35\text{ pts}$).
* **Directed Circular Laundering (Cycles):**
  Flags loops ($A \rightarrow B \rightarrow C \rightarrow A$) using directed simple cycle detection ($+40\text{ pts}$).
* **Automated Quarantine:** If $S_{\text{graph}} \ge 70.0$, the recipient node is locked in `quarantined_accounts`. Subsequent transfers to quarantined nodes automatically receive a $100.0$ risk score.

### 3.3 Coercive Context Engine (`nlp_engine.py`)
Scans text in **0.02 ms** using a multi-category compiled regex taxonomy:
* **Authority Impersonation:** `CBI`, `Cyber Police`, `Interpol`, `Customs`, `Supreme Court`, `Digital Arrest`, `Non-bailable warrant` ($+45\text{ pts}$).
* **Fraudulent Routing:** `Safe Escrow`, `Safe Government Account`, `Verification Account`, `Reserve Account` ($+35\text{ pts}$).
* **Urgency & Isolation:** `Do not disconnect call`, `remain on camera`, `keep confidential`, `immediate liquidation` ($+25\text{ pts}$).
* **Synergy Penalty:** If $\ge 2$ categories match simultaneously ($+15\text{ pts}$).

### 3.4 Unified Policy Engine (`policy_engine.py`)
* **Base Formula:**
  $$R(T) = 100 \times \left( 0.45 \cdot S_{\text{acoustic}} + 0.40 \cdot S_{\text{graph}} + 0.15 \cdot S_{\text{nlp}} \right)$$
* **Missing Modality Normalization:** If no audio is present (online transfer), weights dynamically renormalize over active signals ($w_{\text{graph}}' \approx 0.73, w_{\text{nlp}}' \approx 0.27$).
* **Critical Single-Vector Overrides:**
  * If $S_{\text{acoustic}} \ge 85.0 \rightarrow$ Enforce `HOLD` (Composite risk boosted to $\ge 75.0$).
  * If $S_{\text{graph}} \ge 85.0 \rightarrow$ Enforce `HOLD` (Composite risk boosted to $\ge 78.0$).
  * If $S_{\text{nlp}} \ge 80.0$ AND $S_{\text{graph}} \ge 20.0$ (Digital arrest targeting a new account) $\rightarrow$ Enforce `HOLD` ($\ge 78.0$).

---

## 4. API Surface & Data Contracts

| Method | Endpoint | Description | Latency Benchmark |
| :--- | :--- | :--- | :---: |
| `GET` | `/health` | Service status, active WS connections, target SLA | $< 0.5$ ms |
| `GET` | `/api/v1/metrics` | Operational stats (evaluated, allowed, held, avg latency) | $< 0.5$ ms |
| `POST` | `/api/v1/intercept` | Synchronous in-line transaction evaluation gateway | **1.2 – 2.5 ms** |
| `GET` | `/api/v1/scenarios` | Lists the 4 preset attack scenarios | $< 0.5$ ms |
| `POST` | `/api/v1/scenarios/trigger/{id}` | Triggers a preset attack scenario & broadcasts to WS | **3.0 – 8.0 ms** |
| `GET` | `/api/v1/graph/mule-network` | Returns Cytoscape.js directed graph JSON `{nodes, edges}` | $< 1.0$ ms |
| `POST` | `/api/v1/soc/override` | Manual analyst freeze (`CONFIRM_FREEZE`) or release (`RELEASE_HOLD`) | $< 0.5$ ms |
| `WS` | `/ws/soc-stream` | Real-time bi-directional WebSocket event feed | Real-time |

### In-Line Intercept Schema (`POST /api/v1/intercept`)
```json
// Request Body
{
  "transaction_id": "TX-9921",
  "sender_account": "ACC-ALICE-12",
  "recipient_account": "ACC-MULE-44",
  "amount": 250000.0,
  "channel": "UPI", // "UPI" | "IMPS" | "WIRE" | "NEFT" | "RTGS" | "CARD"
  "recipient_account_age_days": 12,
  "narrative_context": "CBI Digital Arrest verification transfer",
  "audio_base64": "UklGRi..." // Optional Base64 WAV buffer
}

// Response Body
{
  "transaction_id": "TX-9921",
  "decision": "HOLD", // "ALLOW" | "STEP_UP" | "HOLD"
  "composite_risk": 82.5,
  "latency_ms": 1.45,
  "reasons": [
    "HIGH-PRIORITY OVERRIDE: Severe coercive extortion (Digital Arrest) targeting high-risk destination account.",
    "[Graph] Destination account is newly provisioned (12 days old).",
    "[Context] Authority impersonation cues detected: CBI, Digital Arrest."
  ],
  "breakdown": {
    "acoustic_score": 0.0,
    "graph_score": 25.0,
    "nlp_score": 100.0,
    "composite_risk": 82.5
  },
  "acoustic_diagnostics": {
    "is_synthetic": false,
    "confidence": 0.0,
    "spectral_flatness": 0.0,
    "spectral_entropy": 0.0,
    "spectral_rolloff": 0.0,
    "high_freq_ratio": 0.0
  },
  "graph_diagnostics": {
    "is_mule_ring": false,
    "hop_count": 1,
    "dispersion_velocity": 0.0,
    "cycle_detected": false,
    "quarantined_nodes": ["ACC-MULE-44"]
  }
}
```

---

## 5. The 4 Canonical Attack Scenarios

1. **`SCENARIO_1_BASELINE` (Clean Recurring Payment):**
   * *Telemetry:* ₹25,000 IMPS to established supplier (age 420 days), authentic human voice clip.
   * *Expected Decision:* `ALLOW` (Composite Risk: 0.0 – 15.0).
2. **`SCENARIO_2_VOICE_CLONE` (CEO Voice Clone Wire Scam):**
   * *Telemetry:* ₹850,000 WIRE authorized via synthesized vocoder voice clip with high-frequency leakage >4kHz.
   * *Expected Decision:* `HOLD` (Acoustic Score: 100.0, Composite Risk: 78.0 – 85.0).
3. **`SCENARIO_3_MULE_RING` (5-Hop Rapid Mule Ring):**
   * *Telemetry:* ₹500,000 UPI to account that disperses funds through 5 child nodes in <45 seconds.
   * *Expected Decision:* `HOLD` (Graph Score: 90.0, Hop Depth: 5, Recipient Auto-Quarantined).
4. **`SCENARIO_4_DIGITAL_ARREST` (Digital Arrest Coercive Extortion):**
   * *Telemetry:* ₹620,000 RTGS liquidation to newly opened account with CBI arrest warrant script.
   * *Expected Decision:* `HOLD` (NLP Score: 100.0, Composite Risk: 78.0 – 85.0).

---

## 6. Frontend SOC Command Console Design Specification

The frontend delivers a **Dual-Perspective Experience**:
* **View A: Customer / Retail Banking Portal:**
  * Clean modern retail banking UI (send money, recipient, amount, transfer remark).
  * Out-of-band Voice Authorization Widget: Live microphone recorder (Web Audio API) or 1-click test sample picker (Authentic Human Voice vs. Cloned Voice).
  * Instant transaction feedback: Green "Payment Approved" vs. Red "Transaction Intercepted & Frozen".
* **View B: Enterprise Bank SOC Intelligence Dashboard:**
  * Live WebSocket transaction feed with animated status pills.
  * Interactive **Cytoscape.js** directed graph visualizer rendering mule rings with pulsing red quarantine highlights.
  * Live **HTML5 Canvas Spectrogram** plotting audio frequencies and highlighting $> 4\text{ kHz}$ vocoder leakage.
  * Forensic Explainability Drawer displaying mathematical score breakdowns and matched legal coercion keywords.
  * Operational Analyst Overrides: One-click `[Confirm Freeze]` or `[Release Hold]`.
