# Model engineering

The scoring pipeline belongs to the payment plane in [Figure 1](agentic.pdf). The SOC reads versioned evidence through scoped MCP tools. Decision-time snapshots remain auditable.

| Component | Candidate and evaluation |
|---|---|
| Voice | Fine-tune facebook/wav2vec2-base or microsoft/wavlm-base-plus. Review ASVspoof 2019/2021, WaveFake, In-the-Wild and Fake-or-Real. Split by speaker, source and generator. Evaluate unseen codecs including 8 kHz bandwidth, noise and WebRTC capture. Report false spoof alarms, detection at operating point and EER. |
| ASR | Start with openai/whisper-small through faster-whisper. Verify distilled variants for Hindi and Kannada before adoption. Report WER and fraud phrase recall by English, Hindi, Kannada and code switching. |
| Coercion | Tune XLM-R on multilabel authority impersonation, escrow routing, transfer demands and urgency. Benchmark the narrative’s MoritzLaurer DeBERTa zero-shot candidate for multilingual suitability. Include benign mentions, negation and bad ASR. Cite evidence spans with transcript or remark provenance. |
| Mule | Compare PyTorch Geometric GNN with rules and a tabular feature baseline. [Graph design](graph.md) |
| Fusion | Start with logistic regression and compare gradient boosting. Use out-of-fold detector predictions, quality and explicit availability. Calibrate separately and report PR-AUC, reliability, false holds, missed loss and step-up rates by channel. |

Verify licences, model cards, checkpoint revisions and consent before collecting or using datasets. Record lineage, grouped splits, artifacts, reproducible configs and metrics. Synthetic fixtures assist training and regression. Reserve independently adjudicated evaluation data. Aggregate recent spoof scores with quality and a bounded peak. Deduplicate overlapping windows. Associate coercion with a transcript revision. Require calibration and shadow results before enabling any new override. Optional ECAPA speaker enrollment requires separate consent and evaluation.

SOC query intent is typed, read-only and allowlisted. The server validates tenant, date range, depth and result cap and runs parameterized queries. Treat transcript text as untrusted evidence. Copilot cites exact evidence IDs and reports missing evidence. Evaluate isolation and citation accuracy. Payment and analyst controls own writes.
