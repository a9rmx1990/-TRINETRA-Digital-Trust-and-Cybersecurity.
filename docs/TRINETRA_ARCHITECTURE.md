# TRINETRA: Digital Trust & Cybersecurity

> Historical reference. See the [primary architecture](agentic.pdf), [active phases](plan.md) and [runtime](runtime.md).
## Architectural Whitepaper, Operational Working Process, and Technical Specification

> **Track:** Digital Trust and Cybersecurity  
> **Status:** Consensus Architecture Specification (Ready for Hackathon Prototype Build)  
> **LaTeX Source:** [`docs/trinetra_architecture.tex`](file:///home/a9rmx_1990/hackathon/docs/trinetra_architecture.tex)

---

## 1. Executive Summary & Problem Formulation

### 1.1 The Emerging Threat Vector
The rapid democratization of Generative AI has broken traditional perimeter and credential-based banking cybersecurity. Fraud syndicates in 2025–2026 exploit **three zero-day attack vectors**:
1. **AI Voice Clone Impersonation:** Neural vocoders and zero-shot voice cloning (trained on <5 seconds of harvested audio) impersonate executives or family members to authorize out-of-band high-value wire transfers.
2. **"Digital Arrest" & Coercive Extortion:** Algorithmic social engineering presenting fake law enforcement credentials (CBI, Interpol, Police) intimidating victims into liquidating accounts into "safe state escrow" wallets.
3. **Syndicated Multi-Hop Mule Networks:** Coordinated rings that rapidly disperse stolen funds across 5–10 hops of newly provisioned or dormant bank accounts in under 45 seconds, making post-settlement freezing impossible.

### 1.2 The Critical Deficiency of Legacy Anti-Fraud Systems
Legacy banking engines (e.g., rule-based AML, FICO Falcon) evaluate transactions in isolated relational tables. When a victim is coerced or an authorization call is mimicked by an AI clone, **the credentials used are valid and authentic**. Existing systems are:
- **Blind to In-Call Generative Forensics:** Audio is not analyzed for synthetic vocoder artifacts in the transaction loop.
- **Blind to Graph Topology:** Recursive multi-hop cycle searches take minutes in SQL databases, while funds move in seconds.
- **Purely Reactive:** Alerts are raised after funds have settled and dissipated.

---

## 2. System Architecture

TRINETRA operates as an in-line, sub-150ms **Digital Trust Banking Middleware** paired with an **Enterprise SOC Command Console**.

```
                           ┌────────────────────────────────────────┐
                           │      Incoming Telemetry Ingestion      │
                           │  - Transaction Payload (UPI/Card/NEFT) │
                           │  - Out-of-band Audio / Call Stream     │
                           │  - Coercive Message / Script Context   │
                           └──────────────────┬─────────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
     ┌────────────────────────────────┐              ┌────────────────────────────────┐
     │   Graph Intelligence Engine    │              │  Multimodal Forensics Engine   │
     │  (NetworkX / Directed Topology)│              │     (PyTorch / Librosa STFT)   │
     │  - k-hop shortest path search  │              │  - LFCC & spectral flatness    │
     │  - Dispersion velocity ratio   │              │  - Phase continuity anomaly    │
     │  - Mule ring cycle detection   │              │  - Voice clone confidence score│
     └────────────────┬───────────────┘              └────────────────┬───────────────┘
                      │                                               │
                      └───────────────────────┬───────────────────────┘
                                              ▼
                      ┌───────────────────────────────────────────────┐
                      │    Unified Risk Aggregator & Policy Engine    │
                      │  R(T) = w1*S_acoustic + w2*S_graph + w3*S_nlp │
                      └───────────────────────┬───────────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
     ┌────────────────────────────────┐              ┌────────────────────────────────┐
     │   Dynamic Policy Interception  │              │    Enterprise SOC Console      │
     │  - Instant Transaction Hold    │              │  - WebSocket Real-Time Stream  │
     │  - Dynamic Biometric Step-Up   │              │  - Cytoscape.js Mule Ring Graph│
     │  - Target Mule Node Lockdown   │              │  - Audio Spectrogram Heatmap   │
     └────────────────────────────────┘              └────────────────────────────────┘
```

---

## 3. Core Engine Components

### 3.1 Acoustic & Synthetic Voice Forensics
- **Linear Frequency Cepstral Coefficients (LFCC):** Extracts spectral artifacts that neural vocoders (HiFi-GAN, WaveGlow) fail to smooth out in high-frequency bands.
- **Spectral Roll-Off & Energy Entropy:** Detects unnatural uniformity characteristic of text-to-speech synthesis.
- **Real-Time Confidence Scoring:** Outputs $S_{\text{acoustic}} \in [0, 1.0]$.

### 3.2 Graph-Based Mule Ring Engine
- **Topology Analysis:** Maintains an in-memory directed multi-graph of recent transactions.
- **Velocity Ratio ($V_{\text{disp}}$):** Evaluates $\frac{\sum \text{Outflow}}{\sum \text{Inflow} + \epsilon} \cdot \frac{1}{\Delta t}$ to flag rapid cashing out.
- **Cycle & Hop Detection:** Traces funds circulating through shell wallets before reaching crypto ramps or ATM cash-outs.

### 3.3 Dynamic Friction & Policy Decisioning
- **Score < 35 (Low):** Allow through instant payment rail.
- **Score 35–69 (Medium):** Inject dynamic friction (request biometric liveness check or prompt user with verified anti-scam challenge).
- **Score >= 70 (Critical):** Immediate automated transaction hold + simultaneous lockdown of the destination mule account + push to Tier-1 SOC queue.

---

## 4. Why TRINETRA is Different

| Feature | Legacy Rule Engines | Standalone Deepfake Scanners | TRINETRA Hybrid Engine |
| :--- | :--- | :--- | :--- |
| **Telemetry Ingested** | Tabular transaction fields only | Standalone audio/video files | Multi-signal: Transaction + Audio + Graph + Script |
| **Detection Target** | Card theft, velocity limits | Post-mortem media fakes | Real-time AI social engineering & mule rings |
| **Response Latency** | ~100 ms | 10–60 seconds (batch) | **<150 ms (in-line real-time evaluation)** |
| **Mule Ring Tracing** | Single-node threshold checks | Not available | **Multi-hop directed graph traversal** |
| **Intervention** | Binary Pass/Fail | Passive report | **Dynamic friction: Hold, step-up, or alert** |
| **Explainability** | Opaque rule code | Visual bounding box | **Interactive threat graph + frequency spectrogram** |

---

## 5. Technology Stack

- **Backend Middleware:** Python 3.11, FastAPI (asynchronous ASGI), WebSockets, Pydantic v2.
- **Forensic & Data Engines:** PyTorch, Librosa, SciPy, NetworkX.
- **Frontend SOC Dashboard:** Next.js 14 (App Router), React, Tailwind CSS, Lucide React.
- **Interactive Visualizations:** Cytoscape.js (for reactive graph topology), HTML5 Canvas (for audio spectrograms), Recharts.
- **Demo Scenarios:** Embedded Attack Simulator with three realistic attack feeds (Voice Clone, 5-Hop Mule Network, Digital Arrest Extortion).

---

## 6. Scientific Literature Citations (via OpenAlex)

1. **H. Tak, J. Patino, A. Nautsch, N. Evans, and M. Todisco (2021).** *"End-to-end spectro-temporal graph attention networks for speaker verification anti-spoofing and speech deepfake detection."* Proc. ASVspoof Workshop 2021. [DOI: 10.21437/asvspoof.2021-1](https://doi.org/10.21437/asvspoof.2021-1)
2. **N. M. Müller, F. Dieckmann, P. Sizov, and K. Böttinger (2022).** *"Does Audio Deepfake Detection Generalize?"* Proc. Interspeech 2022. [DOI: 10.21437/interspeech.2022-108](https://doi.org/10.21437/interspeech.2022-108)
3. **A. Albakri, E. Boiten, and R. Smith (2021).** *"Financial Cybercrime: A Comprehensive Survey of Deep Learning Approaches to Tackle the Evolving Financial Crime Landscape."* IEEE Access. [DOI: 10.1109/access.2021.3134076](https://doi.org/10.1109/access.2021.3134076)
4. **A. Rössler et al. (2019).** *"FaceForensics++: Learning to Detect Manipulated Facial Images."* Proc. IEEE/CVF ICCV 2019. [DOI: 10.1109/iccv.2019.00009](https://doi.org/10.1109/iccv.2019.00009)
