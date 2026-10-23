# Evaluation

*Synthetic data only. This document reports checks that were actually run and says what was not.*

## What is and is not evaluated
| Layer | Status |
|---|---|
| Workflow behaviour: rules, tools, state, idempotency, isolation, review workflow | **Evaluated**: 35 deterministic checks, each on a fresh seeded database |
| Navigation and selection (customer stays selected, guided demos open the right customer and task, evaluation view stays selected) | **Evaluated** with Streamlit AppTest clicks (19 UI tests) |
| Optional model-backed adapter (hidden in the demo): tool loop, errors, step limit, account boundary | **Evaluated with a fake provider client** (4 tests, no network) |
| Behaviour of a real language model | **Not evaluated and not demonstrated.** The demo is a simulation using prepared scenarios and rules |
| Language quality of messages and recommendations | **Not evaluated.** The app records human 1-5 ratings; none are recorded in this repository |
| Business impact: time saved, learning lift, revenue | **Not evaluable** on synthetic data and not claimed |

Workflow tests are not a language-quality evaluation and must not be cited as one.

## Methodology
Each workflow check builds a new seeded database, drives the real services and tools, then asserts on stored state (messages, tasks, recommendations, feedback, journey state, scheduled actions, guard log, tool executions). The same functions back the **Evaluation → System evaluation → Run workflow checks** button, `python -m cso.evaluation` and `pytest`, so each check has one definition. UI tests drive the full app through button clicks and assert on session state and database rows, not only on text.

## Results: workflow checks (last run)
| # | Check | Result | Evidence from the run |
|---|---|---|---|
| 01 | Future rollout pauses outreach | Pass | state=paused_until_rollout, agent messages sent=0 |
| 02 | Completed setup stops reminders | Pass | pending reminders 1 -> 0, state=completed |
| 03 | Open support case prevents duplicate escalation | Pass | open tasks 1 -> 1; duplicate_prevented logged=1 |
| 04 | Opt-out blocks outbound messages | Pass | direct send -> ok=False (policy_blocked); messages after agent check=0 |
| 05 | Previously attempted guidance is not repeated | Pass | guidance docs ['DOC-105'] recorded as attempted ['DOC-105']; resend -> repeat_guidance |
| 06 | Unsupported documentation question gets a fallback | Pass | fallback message explains the limit and offers a specialist; no sources attached |
| 07 | Email-to-chat switch preserves customer context | Pass | history seen by chat reply included email message INT-0024; reply channel=chat |
| 08 | Failed handoff tool does not produce a false success claim | Pass | tasks created=0; tool error=tool_unavailable; message admits failure=True |
| 09 | Repeated trigger does not duplicate a message | Pass | two calls with one key -> second deduplicated=True; two agent checks afterwards; messages=1 |
| 10 | Repeated escalation does not duplicate a task | Pass | open tasks after two different-key escalations=1; second flagged existing=True |
| 11 | Missing essential context prevents unsupported outreach | Pass | No outreach: Missing essential data: administrator contact email. Flagged for review instead of guessing. |
| 12 | Support resolution causes a fresh product-progress check | Pass | progress_check run tools=['get_customer_context', 'get_setup_progress', 'get_interaction_history', 'check_support_cases', 'resume_journey', 'search_documentation', 'send_guidance', 'update_journey_status']; journey state |
| 13 | One customer's information is never returned for another | Pass | cross-account calls -> ['account_boundary', 'account_boundary', 'account_boundary']; history rows from other accounts=0 |
| 14 | A message attempting to override policies is rejected | Pass | override logged=1; messages added=1 (only to the sender); tools used=['check_support_cases', 'get_customer_context', 'get_interaction_history', 'get_setup_progress', 'send_guidance'] |
| 15 | Frequency limits prevent excessive outreach | Pass | proactive messages sent=1 with limit 1/7 days; second run: No outreach: 1 of 1 proactive messages used in 7 days; minimum gap 48h. |
| 16 | Already-completed training is not recommended again | Pass | action=discovery, no courses; direct re-recommendation -> already_completed |
| 17 | Unmet prerequisites lead to the prerequisite first | Pass | direct CRS-102 -> prerequisite_unmet; assistant recommended ['CRS-101'] (the prerequisite) |
| 18 | Missing or stale learner data leads to a clarification | Pass | results [('missing_learners', 'clarify'), ('stale_learners', 'clarify')] |
| 19 | A technical blocker leads to technical follow-up | Pass | action=technical_followup; no training recommended while the blocker is open |
| 20 | Dismissed and deferred recommendations are respected | Pass | dismissed: 'No recommendation saved: REC-007 was dismissed (Wrong timing); not rec'; recs stayed at 1/1; deferred: 'No recommendation saved: REC-008 was deferred (Wrong timing); leave it'; total recs=1 |
| 21 | Repeated scans do not duplicate recommendations | Pass | first scan created 7 recommendation(s); repeating the scan left it at 7 |
| 22 | Account isolation holds for Account Team tools | Pass | cross-account Account Team calls -> ['account_boundary', 'account_boundary', 'account_boundary'] |
| 23 | Invalid course or evidence citations are rejected | Pass | unknown course -> invalid_input; evidence never gathered -> unsupported_evidence |
| 24 | Accepting a recommendation does not create enrolment | Pass | status=accepted; learner records unchanged (10 rows); enrolment outcomes=0 |
| 25 | Edits preserve the original recommendation | Pass | original text preserved in the recommendation and the feedback record; revised text stored separately |
| 26 | Meeting cancellation withdraws pending recommendations | Pass | withdrawn=1; status=withdrawn; after cancellation: 'The meeting is cancelled or already past, so no meeting-specific recom' |
| 27 | Unsupported claims are excluded from recommendations | Pass | training claim without learner-record and catalog evidence -> unsupported_evidence; no evidence at all -> unsupported_evidence |
| 28 | Paid options need a justification and free alternatives | Pass | paid course without justification -> paid_needs_justification; assistant's paid recommendation records free alternatives considered |
| 29 | Review actions and tool allow-lists are enforced | Pass | agent cannot record review actions (tool_not_permitted); tools outside the workflow's allow-list refused (tool_not_permitted); status stays generated |
| 30 | Policy blocks, technical failures and duplicates are counted separately | Pass | success=17, expected policy blocks=1, technical failures=1, duplicates=0 (counted separately) |
| 31 | Unknown error: one clarifying question, then only the matching, cited section | Pass | unknown error -> one clarifying question; after 'authentication error' -> ['DOC-105'] cited ['DOC-105'] (only the matching section); proactive message cites ['DOC-102', 'DOC-104'] and lists ['DOC-102', 'DOC-104'] |
| 32 | A changed meeting date refreshes the recommendation | Pass | old recommendation flagged then withdrawn (withdrawn); new one REC-008 generated for the new date |
| 33 | Brief views are not counted on rerenders | Pass | three view events for one reviewer counted as 1 |
| 34 | Prospects get no invented usage or training | Pass | prospect has 0 usage events and 0 learner records; recommendation type=discovery with no training invented |
| 35 | A completion claim without matching product events keeps the journey open | Pass | claim without events -> journey stays 'waiting_for_customer' (assistant says it does not see the steps; reminders pending=1); claim after events exist -> 'completed' (reminders pending=0) |

**35 of 35 passed.**

## Results: full test suite
`pytest` → **64 passed**: 41 in `tests/test_workflows.py` (35 workflow cases and 6 supporting tests: seed determinism and size, transition table, invalid or injected tool input, completion needs progress evidence, tool schema set, retrieval ranking and off-topic fallback), 19 in `tests/test_ui.py`, 4 in `tests/test_live_adapter.py`.

The UI tests cover: every page renders; the selected customer and product survive an action and navigation between pages; Customer and Agent pages show the same customer; the Maple guided demo opens the right customer; the full guided journey by clicks (plain reruns send nothing, the handoff link opens the exact task, a resolution note is required, resolving does not complete onboarding, return-to-journey works); the queue does not default to another customer's task; the Evaluation view stays selected after running checks and shows the result; restarting one walkthrough keeps the other's progress; accepting after an edit is recorded explicitly and the review message follows the status; a typed completion claim without product events keeps the journey open; reviewer-only features are hidden by default; a failed handoff is reported honestly and can be retried; every walkthrough screen names the role you are playing; the Northstar guided flow (reruns create nothing, edit preserves the original, accepting creates no enrolment or outcome).

## Account Team measures (definitions)
Observed in session: eligible meetings (scheduled in the next 14 days), briefs generated, briefs viewed (one per reviewer per meeting; reruns are not counted), recommendations reviewed, accepted / edited / dismissed / deferred, marked discussed, and synthetic learner enrolment / start / completion counts. Each row on the Evaluation page states its denominator. Seeded history is shown separately and labelled synthetic.

## Human scoring
Message criteria (1-5): relevance, groundedness, correctness, instruction following, helpfulness, clarity. Recommendations add: timing, fit to role and goal, prerequisite compatibility, usefulness of the next action. Until a person records ratings the app shows "not evaluated".

## Limits of synthetic demonstrations
- Seeded customers follow scripts I wrote; passing checks show the rules do what they claim, not that they suit real customers.
- Keyword reply screening, TF-IDF retrieval and token-overlap catalog search are shallow; real language is messier.
- Seeded outcomes cannot show either workflow changes anything. A real pilot could compare briefed and unbriefed comparable meetings, time sample preparations, track field adoption and follow learning outcomes, with randomisation or a clear comparison group.
- Scheduling, delivery, consent, calendar, CRM and learning-system data are simulated.
