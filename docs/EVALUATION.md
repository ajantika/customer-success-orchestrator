# Evaluation

*Synthetic data only. This document reports checks that were actually run and says what was not.*

## What is and is not evaluated
| Layer | Status |
|---|---|
| Workflow behaviour (rules, tools, state, idempotency, isolation) | **Evaluated**: 15 deterministic checks, all run against a fresh seeded database each |
| Supporting unit and UI tests | **Evaluated**: see below |
| Live AI wiring (tool loop, errors, step limit) | **Evaluated with a fake provider client** (no network) |
| Live model behaviour with a real API key | **Not evaluated.** An optional runner exists (`python -m cso.evaluation --live`) but was not run |
| Language quality of messages (relevance, groundedness, correctness, instruction following, helpfulness, clarity) | **Not evaluated.** The app supports recording human 1-5 ratings; none are recorded in this repository |
| Business impact | **Not evaluable** on synthetic data |

Workflow tests are not a language-quality evaluation and must not be cited as one.

## Methodology
Each check builds a new seeded database (`build_db()`), drives the real services/tools, then asserts on stored state (messages, tasks, journey state, scheduled actions, guard log, tool executions). The same functions back the **Evaluation → Run 15 workflow checks** button, `python -m cso.evaluation` and `pytest`, so there is one definition of each check.

## Results: workflow checks (last run)
| # | Check | Result | Evidence from the run |
|---|---|---|---|
| 01 | Future rollout pauses outreach | PASS | state=paused_until_rollout, agent messages sent=0 |
| 02 | Completed setup stops reminders | PASS | pending reminders 1 -> 0, state=completed |
| 03 | Open support case prevents duplicate escalation | PASS | open tasks 1 -> 1; duplicate_prevented logged=1 |
| 04 | Opt-out blocks outbound messages | PASS | direct send -> ok=False (policy_blocked); messages after agent check=0 |
| 05 | Previously attempted guidance is not repeated | PASS | guidance docs ['DOC-105'] recorded as attempted ['DOC-105']; resend -> repeat_guidance |
| 06 | Unsupported documentation question gets a fallback | PASS | fallback message explains the limit and offers a specialist; no sources attached |
| 07 | Email-to-chat switch preserves customer context | PASS | history seen by chat reply included email message INT-0024; reply channel=chat |
| 08 | Failed handoff tool does not produce a false success claim | PASS | tasks created=0; tool error=tool_unavailable; message admits failure=True |
| 09 | Repeated trigger does not duplicate a message | PASS | two calls with one key -> second deduplicated=True; two agent checks afterwards; messages=1 |
| 10 | Repeated escalation does not duplicate a task | PASS | open tasks after two different-key escalations=1; second flagged existing=True |
| 11 | Missing essential context prevents unsupported outreach | PASS | No outreach: Missing essential data: administrator contact email. Flagged for review instead of guessing. |
| 12 | Support resolution causes a fresh product-progress check | PASS | progress_check run tools=['get_customer_context', 'get_setup_progress', 'get_interaction_history', 'check_support_cases', 'resume_journey', 'search_documentation', 'send_guidance', 'update_journey_status']; journey state after res |
| 13 | One customer's information is never returned for another | PASS | cross-account calls -> ['account_boundary', 'account_boundary', 'account_boundary']; history rows from other accounts=0 |
| 14 | A message attempting to override policies is rejected | PASS | override logged=1; messages added=1 (only to the sender); tools used=['check_support_cases', 'get_customer_context', 'get_interaction_history', 'get_setup_progress', 'send_guidance'] |
| 15 | Frequency limits prevent excessive outreach | PASS | proactive messages sent=1 with limit 1/7 days; second run: No outreach: 1 of 1 proactive messages used in 7 days; minimum gap 48h. |

**15 of 15 passed.**

## Results: full test suite
`pytest` → **34 passed**: 15 workflow cases, 6 supporting tests (seed determinism and size, transition table, rejection of invalid or injected tool input, completion needs progress evidence, tool schema set, retrieval ranking and off-topic fallback), 9 UI tests with Streamlit's AppTest (every page renders; guided journey through real button clicks; reruns send nothing; the operator note is required; reset restores seed state), 4 live-adapter tests with a fake client (tool results fed back, cross-account call refused, API failure reported without scripted substitution, step limit).

## Human scoring
Criteria (each 1-5, recorded per message on the Evaluation page):
- **Relevance**: addresses what the customer said or needs next.
- **Groundedness**: product claims are supported by the cited documents.
- **Correctness**: facts and steps are right and match what tools actually did.
- **Instruction following**: respects objective, policies, channel and tone.
- **Helpfulness**: moves the customer toward the milestone.
- **Clarity**: short, plain, actionable.

Until a person records ratings the app shows "not evaluated". No scores are generated automatically.

## Limits of synthetic demonstrations
- Seeded customers follow scripts I wrote; passing checks shows the rules do what they claim, not that they suit real customers.
- Keyword reply screening and TF-IDF retrieval are shallow; real language is messier.
- Seeded "outcomes" are generated, so they cannot show that the agent improves anything. A production pilot would compare agent-assisted accounts with a randomised holdout on a pre-registered metric, with opt-out and complaint rates as guardrails.
- Scheduling, delivery, consent and data latency are simulated.
