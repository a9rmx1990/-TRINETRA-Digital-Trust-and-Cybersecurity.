# Prototype inventory

> Historical reference. See the [primary architecture](agentic.pdf), [active phases](plan.md) and [runtime](runtime.md).

| Source | Current behavior and migration impact |
|---|---|
| frontend App, Header, BankingPortal and TransferForm | Banking and SOC tabs, health and metrics polling, client-supplied account age, typed narrative and one-shot submission. Introduce trusted metadata and session correlation. |
| VoiceAuthWidget and OutcomeBanner | Three-second MediaRecorder WebM upload. UI interprets risk decision as dispatch or freeze. Add WebRTC and display confirmed execution state. |
| api.ts, types.ts and useSOCSocket | Localhost URLs, hand-maintained types, reconnect and latest 50 events. Move to configured endpoints and versioned contracts with replay cursors. |
| SOCConsole, LiveFeed, EventDetailDrawer, ScenarioBar, GraphPanel and SpectrogramPanel | Live feed, account override, four scenarios, Cytoscape and partly randomized acoustic bars. Add durable cases and measured frequency evidence or a metrics-only panel. |
| backend main, schemas, config and websocket_manager | FastAPI intercept, health, metrics, scenarios, graph, override and WebSocket. Engines run sequentially. Reported latency excludes awaited broadcast. State and metrics live in process. Introduce independent event delivery and durable state. |
| audio_engine | WAV/PyAV decoding, raw PCM fallback and deterministic acoustic features. Keep diagnostics and demo fixtures. Add validated spoof inference and explicit invalid-audio handling. |
| nlp_engine | English regex on submitted remarks, no ASR. Preserve useful reason categories and add multilingual transcript analysis. |
| graph_engine | DiGraph overwrites parallel edges. Inserts proposed payments and may mutate quarantine during scoring. Separate evidence from enforcement and settled history. |
| policy_engine | Fixed 0.45/0.40/0.15 weights, reason-string missing audio detection and threshold overrides. Replace with typed evidence and versioned calibrated policy. |
| simulator and tests | Clean, spoof, mule and coercion scenarios. Five Python test modules, Python integration runner, Node frontend test and root live integration script. Generated fixtures establish regression behavior. |

[Backend](../backend/app/main.py) · [Frontend](../frontend/src/App.tsx) · [Scenarios](../backend/app/simulator/scenarios.py) · [Historical agent guide](../AGENT.md)
