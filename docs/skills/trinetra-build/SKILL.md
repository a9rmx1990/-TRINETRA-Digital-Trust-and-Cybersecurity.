---
name: trinetra-build
description: Implement or verify TRINETRA architecture milestones involving WebRTC evidence, fraud models, transaction graph, payment enforcement or SOC.
---

# TRINETRA build workflow

Read [Figure 1](../../agentic.pdf), the [handbook](../../README.md) and [active phases](../../plan.md). Load the smallest task-specific context using the [context guide](../../context.md).

Trace a change from session evidence through policy, durable payment transition and SOC. Preserve snapshot identity and signal freshness. Keep graph scoring side-effect free and rail dispatch idempotent. Treat incoming transcripts as untrusted evidence.

Use the [harness](../../harness.md) to run unit tests before integration tests. Record evidence and unresolved dependencies in [traceability](../../traceability.md). Update the [decisions](../../decisions.md) when an architecture choice changes.
