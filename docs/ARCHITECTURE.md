# Architecture

## Shared data architecture
```
Streamlit pages (cso/ui) ──button callbacks only──► services.py (onboarding)  /  team.py (meeting preparation)
                                                          │
                                       rules.ingest_customer_message          agent.run_agent (bounded loop)
                                       (screen + record, no actions)                │ asks a decider for the next tool call
                                                                                    │   ScriptedDecider (rules, "Demo mode") | LiveDecider (model)
                                                                                    ▼
                                                    tools.execute_tool: validation → allow-list → account boundary →
                                                    idempotency → fault injection → run → evidence + audit record
                                                                                    │
                                   ┌──────────────┬────────────────┬────────────────┴───────────────┐
                                   ▼              ▼                ▼                                ▼
                               rules.py     retrieval.py       training catalog              SQLite (in memory, per session)
                          (eligibility,     (TF-IDF over kb/)  (courses, prerequisites)      accounts, subscriptions, rollout plans,
                           transitions)                                                      product events, support cases, interactions,
                                                                                             journeys, tasks, meetings, learner records,
                                                                                             recommendations, feedback, outcomes, runs, tool executions
```
Both workflows use the same account, product-event, support-case, documentation and rules layers. The Meeting-preparation workflow adds meetings, learner records, a course catalog, recommendations and review feedback.

## Agent, tools and allowed actions
One loop, two permitted tool sets (enforced per run by an allow-list):

| Tool | Workflow | Type | Notes |
|---|---|---|---|
| get_customer_context | both | read | goal, plan, journeys, masked contact, eligibility with reasons |
| get_setup_progress | both | read | milestones from product events, freshness, 14-day vs prior-30-day activity |
| get_interaction_history | onboarding | read | cross-channel messages, tried and sent documents |
| search_documentation | both | read | TF-IDF; `supported` flag; records which documents (and cross-references) were retrieved |
| check_support_cases | both | read | open cases and tasks |
| send_guidance | onboarding | write | kinds: proactive, reply, status update, confirmation; rules can refuse; citations validated |
| pause_journey / resume_journey | onboarding | write | cancel or schedule reminders |
| create_handoff | onboarding | write | one open task per product; full context |
| update_journey_status | onboarding | write | completion needs fresh progress; opt-out cascades |
| get_meeting_context | Meeting prep | read | purpose, date, owner, changed/cancelled/past, lifecycle stage |
| get_learning_progress | Meeting prep | read | learner records per course, freshness, missing data |
| search_training_catalog | Meeting prep | read | courses, prerequisites, free or paid, availability |
| get_account_blockers | Meeting prep | read | open cases/tasks, rollout status, earlier recommendations (dismissed/deferred) |
| save_recommendation | Meeting prep | write | validates evidence, courses, prerequisites, paid justification, duplicates |
| record_recommendation_feedback | **human only** | write | review, accept, edit, dismiss, defer, discuss; refused for agent runs |

Inputs and outputs are Pydantic models (`extra="forbid"`). There is no free-form SQL or code execution. The agent cannot send real email, enrol, schedule or buy.

## Evidence and citations
Read tools return evidence items (ID, label, source, timestamp). `save_recommendation` accepts only evidence IDs gathered in that run, and a training recommendation must cite learner-record and catalog evidence. `send_guidance` rejects a message that cites a document ID it does not list, and a listed document that was not retrieved in the run. Documents referenced inside an excerpt (for example "see DOC-104") are retrievable cross-references and appear as sources too.

## State models
**Customer journey** (separate from milestone status, which comes from product events)
```
monitoring ─► guidance_sent ─► waiting_for_customer ─┐
   │  ▲            │                  │              │
   │  └────────────┴──────────────────┘              │
   ├─► paused_until_rollout ◄──(pause_journey)───────┤
   ├─► waiting_for_human ─► resolved_awaiting_progress_check ─► monitoring / guidance_sent / waiting_for_customer
   └─► completed (terminal)      opted_out (terminal)  ◄── reachable from every non-terminal state
```
**Recommendation**
```
generated ─► reviewed ─► accepted ──► discussed (terminal)
    │            │          ▲ │
    │            ├─► edited ┘ └─► dismissed (terminal, reason required)
    │            ├─► deferred ─► reviewed / accepted / edited / dismissed   (reason required)
    └─► (acting directly records "reviewed" first)        withdrawn (system: meeting cancelled or date changed)
```
**Customer learning outcomes** (enrolled, started, completed) live in learner records and a separate outcomes table. No recommendation transition writes to them.

## Human review and feedback
Every action writes a feedback record: recommendation ID, account ID, meeting ID, reviewer (sample identity), action, reason, note, timestamp, original content and revised content. The original recommendation text is never overwritten. A feedback summary (dismissal reasons, edited recommendations, accepted-but-not-discussed, repeated information gaps) supports roadmap decisions. Nothing feeds back into agent policy automatically.

## Selection and navigation
Selected customer, product, task, meeting, reviewer and the active view live in plain session keys. Widgets mirror those values every run and update them through `on_change`. This avoids two Streamlit behaviours that caused the earlier "selector disappeared" bug: widget state is dropped when the widget is not rendered on a run (another page), and a widget is recreated when its option labels change (the earlier product radio put a changing journey status in its labels). Option values are stable IDs. Button callbacks request navigation with `session.goto`, and `app.py` performs the page switch.

## Account isolation, failure handling, time
- Each session has its own in-memory database; API keys live in the session or environment, never the database or UI.
- A run is bound to one account. Tools refuse other accounts, and journey, contact and meeting IDs are checked to belong to it.
- Tools return explicit failures, split in the metrics into expected policy blocks, technical failures and duplicates prevented.
- Idempotency keys, natural de-duplication (open task, existing recommendation) and a step limit protect against retries, reruns and loops.
- A demo clock replaces wall time. Scheduled work runs only when a button is clicked.
