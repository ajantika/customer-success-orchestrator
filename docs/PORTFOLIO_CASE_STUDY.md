# Case study: Customer Success Orchestrator

*A personal prototype built to explore how agentic customer success could work. Fictional company, synthetic data, no real customers or results.*

## Problem
Customers who buy several products adopt them on their own schedule. Success teams want to help when setup stalls, but three things go wrong: outreach ignores the customer's rollout plan, automation collides with open support issues, and handoffs to people lose context. Adding an AI agent makes all three easier to get wrong unless the rules are explicit.

## Product approach
Treat the agent as a **bounded operator inside a rule-enforced system**, not a chatbot. Signals (milestone events, plans, history, cases) feed one onboarding agent. The agent can call ten tools; each tool validates input, enforces account boundaries and consults code-level rules before changing state. A human queue receives escalations with the customer's goal, what was sent and what the customer already tried.

## Agent capabilities
Gathers context, reads fresh progress, retrieves documentation with sources, interprets replies, sends guidance on the customer's channel, pauses/resumes journeys, opens exactly one handoff, completes journeys only on product evidence, honours opt-outs, and refuses policy-override attempts. It stops at completion or a configurable step limit.

## Key decisions
- **Policy in code, not prompts.** The same gate protects Scripted and Live modes.
- **Two modes with honest labels.** A deterministic Scripted mode makes the demo reliable and testable without keys; it never claims to be an LLM.
- **Journey state ≠ milestone status.** "Paused" and "half set up" are different facts.
- **Human resolution ≠ onboarding success.** Resolving a ticket forces a fresh progress check.
- **Fail loudly.** A failed handoff produces a message that says nothing was created.
- **Idempotency everywhere** so reruns and retries can't duplicate messages or tasks.

## What was built and tested
A six-page Streamlit app over a session-isolated SQLite state layer with 40 deterministic synthetic accounts, a 10-document fictional knowledge base with TF-IDF retrieval, ten validated tools, a bounded agent loop, a scripted decider and a live Anthropic decider, a configurable policy, and an evaluation page that separates observed, seeded and evaluated results.
Tested: 15 workflow checks (all passing), plus unit, UI click-through and fake-client live-adapter tests (34 tests in total). See [EVALUATION.md](EVALUATION.md).

## What would need validation in production
- Real-model behaviour: groundedness, tone and escalation judgement under human rating.
- Intent understanding beyond keywords; multilingual replies.
- Thresholds and frequency limits calibrated on real data, per segment.
- Data freshness, event latency and identity matching across systems.
- Consent and regional contact rules.
- Causal impact: a randomised pilot with a holdout, a pre-registered primary metric and guardrails for opt-outs and complaints.
- Operational fit: handoff SLAs, ownership of documentation, and incident response for agent errors.
