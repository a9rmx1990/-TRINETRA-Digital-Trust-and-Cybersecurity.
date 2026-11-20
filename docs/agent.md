# Agent guide

Read the handbook index, active milestone and its acceptance criteria. Use [Figure 1](agentic.pdf) for the architecture, [decisions](decisions.md) for choices, and [runtime](runtime.md) for verified behavior. Follow user scope and applicable repository instructions. The historical root agent guide describes the legacy prototype constraints. Target model work requires explicit milestone scope.

Before editing, identify upstream inputs, downstream consumers, durable writes and rollback. Keep model training and runtime changes independently reviewable. Preserve the sandbox demos as a baseline. Review contract changes across Pydantic, TypeScript, events and integration checks. Release and freeze actions need authenticated actors and audit evidence.

Conclude each milestone with the actual behavior, verification results, artifact versions and remaining work. [Context](context.md) · [Harness](harness.md) · [Loops](loops.md)
