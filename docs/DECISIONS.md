# Decisions

| # | Decision | Alternatives | Why | Revisit when |
|---|---|---|---|---|
| 1 | **Rules live in code, the LLM only proposes** | Put policy in the system prompt | Prompts are not guarantees; code gives tests and a single gate for both modes | Policies become too numerous for hand-written checks (move to a rules engine) |
| 2 | **One agent, many tools** | Multi-agent orchestration | The problem is a single objective with permitted actions; extra agents add handoff failure modes | Distinct objectives (e.g. renewals) appear |
| 3 | **Scripted decider as a first-class mode** | Mock the LLM, or require a key | Public demo without secrets; deterministic tests; honest labelling | Live mode matures enough to be the default |
| 4 | **Generator-based scripted flows** | Giant if/else, or a workflow DSL | Reads like the agent's plan, reacts to each tool result, shares the loop | Flows exceed ~10 branches |
| 5 | **Session-scoped in-memory SQLite** | Shared DB, files, Streamlit state only | Isolation by construction; SQL for audit queries; zero setup | Need persistence across sessions (use a file path) |
| 6 | **Journey state ≠ milestone status** | One status column | Customers can be "paused" while milestones are half done; milestones come from events | State list grows |
| 7 | **Idempotency keys + natural dedupe** | Rely on Streamlit callbacks only | Reruns, double clicks and retries are real; callbacks alone don't cover live retries | A real queue replaces the simulated one |
| 8 | **TF-IDF retrieval** | Embeddings / vector DB | Small corpus, no dependencies, explainable scores | Corpus grows or paraphrase misses appear in evaluation |
| 9 | **Keyword screen for replies** | LLM classifier | Deterministic, zero-cost, testable; known to be shallow | Misclassification shows up in live evaluation |
| 10 | **Human resolution forces a fresh check** | Assume resolved = succeeded | A fixed ticket does not equal a completed milestone | Never; this protects trust |
| 11 | **Completion must be proven by product events** | Trust the customer's "we're done" | Customers misreport; data can lag | A verified self-attestation flow exists |
| 12 | **Handoff failure produces an honest message** | Retry silently | Customers must not be told something that did not happen | A durable retry queue exists |
| 13 | **Demo clock + manual run buttons** | Background scheduler | Streamlit has no reliable scheduler; manual control makes demos legible | Moving to a real deployment |
| 14 | **Anthropic only for live mode** | Multi-provider abstraction | One complete integration beats several partial ones | A second provider is required |
| 15 | **Policy thresholds shown as demo values** | Present as best practice | They are arbitrary; calling them recommendations would mislead | Calibrated from real data |
