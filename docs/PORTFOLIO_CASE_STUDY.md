# Case study: Customer Success Orchestrator

*A personal prototype exploring how agentic assistance could support customer success. Sample company, sample data, no real customers or results. It simulates an agent workflow with prepared scenarios and rules; it demonstrates product and workflow design, not the behaviour of a language model.*

## Why these two workflows
Customer success work has two linked halves. **Customers** need timely, relevant help getting set up. **Sales and customer-success teams** need to walk into conversations knowing the customer's goal and situation. Both depend on the same signals: product usage, rollout plans, support cases, documentation and learning progress. Building both on one data foundation shows reuse, and shows that the hard part is not generating text but deciding *whether* and *when* to act.

## Onboarding approach
A bounded agent with ten tools helps eligible customers. Rules in code decide who may be contacted. When a customer reports a problem without detail, the agent asks one short question before sending instructions, avoids repeating anything already tried, cites the documents it actually retrieved, and hands off to a person with full context. Resolving a ticket forces a fresh progress check rather than assuming success.

## How recommendations fit a sales or customer-success team's work
The assistant prepares a meeting brief and one recommendation where the AE and SA already look: an upcoming-meetings list with the account, owner, purpose and lifecycle stage. The recommendation states the next action, why now, the customer goal it supports, evidence with timestamps, what is still unknown, and a short talking point. It is deliberately phrased as a question to ask ("does the team need help applying the workflow?") because low usage is not proof of a skills gap. It changes shape when facts change: technical blocker first, wait for a delayed rollout, ask for missing learner data, do not repeat completed courses, start with an unmet prerequisite, and justify any paid option against free ones.

## Human review and feedback
The reviewer accepts, edits, dismisses (with a reason), defers or marks the item discussed. The original is preserved next to any edit. Accepting never enrols anyone; learning outcomes are tracked separately. A feedback summary (dismissal reasons, edited recommendations, accepted-but-undiscussed, repeated information gaps) tells a product owner what to improve. It would inform roadmap decisions such as better learner-data capture or catalog gaps. The assistant does not learn from it automatically.

## Key decisions
Policy in code, not prompts. Two modes with honest labels. Evidence IDs and citation checks so claims are supportable. Human-only review actions and per-workflow tool allow-lists. Stable selection state. Evidence completeness instead of fake confidence scores.

## What was built and tested
A seven-page Streamlit app on session-isolated SQLite with 43 sample accounts, a sample training catalog, 16 tools, a deterministic decider (a simulation of an agent workflow; no AI model is called in the demo), and an evaluation page that separates observed, seeded and tested results. 64 automated tests pass, including 35 workflow checks and UI click-through tests. See [EVALUATION.md](EVALUATION.md).

## What must be validated before a production rollout
- Real-model behaviour for both workflows, with human ratings of timing, fit, prerequisite handling and usefulness.
- Whether reviewers find briefs faster and better than their current preparation (time sampling, adoption by role).
- Data quality and freshness of usage, learner and support records, and identity matching across systems.
- Whether recommendations lead to useful conversations and downstream learning, using a randomised or otherwise comparable group.
- Privacy, consent and regional rules for contacting customers and using learner data.
- Operational ownership: catalog upkeep, review workload, incident response for wrong recommendations.
