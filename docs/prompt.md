Caller workflow

> Historical reference. See the [primary architecture](agentic.pdf), [active phases](plan.md) and [runtime](runtime.md).

1. Show a clean landing page with one primary action, “Start a voice session.”
2. Explain why the bank analyzes the audio and ask for consent before accessing the microphone. Let the caller start and end the session. Show clear states for connecting, listening, analyzing, and retrying.
3. After the voice session, take the caller to the payment form. Automatically attach the voice session to the submission. Keep technical scores and fraud rules inside the SOC console.
4. Analyze the audio for signs of AI generation and combine that evidence with the payment risk signals. Use three meaningful outcomes for voice analysis: likely genuine, suspected synthetic, and inconclusive. Handle silence, poor audio, and unavailable models explicitly.
5. Show the caller the actual payment status: submitted, verification required, or under review. Use “settled” only when the payment system confirms it.

SOC workflow

1. Give analysts a separate, authenticated console. Create a case automatically when a payment requires verification or review.
2. Add an AI agent that reviews the case evidence, prioritizes the queue, summarizes what triggered the decision, and recommends the next action. Show the evidence behind each recommendation, including voice analysis, relevant transcript excerpts, and transaction graph signals where available.
3. Let the agent prepare cases and recommendations automatically. Require an authorized analyst to approve actions such as releasing a payment or freezing an account. Record those actions in the audit trail.

Design and delivery

- Use restrained colors, clear typography, consistent spacing, and accessible forms. Make both workflows responsive and keyboard accessible.
- Remove demo scenario buttons and fixture controls from the user-facing experience. Keep fixtures available for automated tests.
- Make microphone denial, dropped sessions, low-confidence results, and service failures recoverable. Use plain banking language throughout.
- Verify the complete flow from voice capture to payment decision and SOC review. Report which paths were tested and which still depend on external services.
- At handoff, list any required model checkpoints, packages, services, and API keys. Give the exact environment variable names and setup steps. Keep credentials on the backend and provide a .env.example with placeholders.

One distinction to preserve: a browser microphone session and a live call with a bank representative are different integrations. TRINETRA currently supports the microphone session. A live representative call needs a telephony or contact center provider. For the existing project, local Whisper, spoof detection, coercion, and graph models use local artifacts configured through TRINETRA_MODELS. The SOC investigator uses local evidence and optionally a self-hosted model. Runtime and model setup (docs/runtime.md)
