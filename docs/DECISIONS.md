# Decisions

| # | Decision | Alternatives | Why | Revisit when |
|---|---|---|---|---|
| 1 | **Rules live in code, the LLM only proposes** | Put policy in the system prompt | Prompts are not guarantees; code gives tests and a single gate for both modes | Policies become too numerous for hand-written checks (move to a rules engine) |
| 2 | **One agent, many tools** | Multi-agent orchestration | The problem is a single objective with permitted actions; extra agents add handoff failure modes | Distinct objectives (e.g. renewals) appear |
| 3 | **Demo mode (rule-based decider) as a first-class mode** | Mock the LLM, or require a key | Public demo without secrets; deterministic tests; honest labelling | Live mode matures enough to be the default |
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
| 16 | **Canonical selection in session keys, widgets mirror it** | Rely on widget keys | Streamlit drops widget state on other pages and recreates widgets whose labels change; stable IDs and mirrored state fix the root cause | Streamlit changes widget persistence |
| 17 | **Meeting recommendations are a hypothesis plus a question, not a diagnosis** | Recommend training directly from low usage | Low usage has many causes; the talking point asks whether help is needed and makes training conditional | Evidence from a pilot that usage alone predicts need |
| 18 | **Evidence IDs gathered in-run are the only citable evidence** | Free-text rationale | Prevents unsupported claims in both demo and live modes | Evidence structure needs to link to a real CRM |
| 19 | **Evidence completeness instead of a confidence percentage** | Show a score | An arbitrary percentage would imply precision that does not exist | Calibrated against reviewer outcomes |
| 20 | **Only humans can record review actions; agent runs have tool allow-lists** | Let the agent self-approve | Review must be a human control; allow-lists limit blast radius | Never for customer-facing proposals |
| 21 | **Accepting is not enrolling; outcomes tracked separately** | Treat acceptance as success | Acceptance means the reviewer agrees to raise it, not that the customer did anything | Real LMS integration |
| 22 | **Original recommendation preserved beside edits** | Overwrite | Product owners learn from what changed | Storage or privacy limits |
| 23 | **Clarify before troubleshooting** | Send all fixes for a vague error | Shorter, less repetitive, avoids already-tried steps | Customers abandon after a question (measure in a pilot) |
| 24 | **Dark theme with one accent palette** | Light default | Reduces glare in demos and keeps charts and tables consistent | Accessibility review finds contrast issues |
| 25 | **Keep the new page count to one** | Separate pages per feature | Meeting-preparation features sit on one page; extensions live in Customer workspace and Evaluation | Page grows past what one view can hold |
