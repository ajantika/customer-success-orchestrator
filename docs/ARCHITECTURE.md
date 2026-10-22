# Architecture

## System diagram
```
Streamlit pages (cso/ui)  ──button callbacks only──►  services.py
                                                         │
                                          ┌──────────────┴───────────────┐
                                          ▼                              ▼
                                   rules.ingest_customer_message    agent.run_agent (bounded loop)
                                   (screen + record, no actions)         │ asks a decider for the next tool call
                                                                         │   ScriptedDecider (rules)  |  LiveDecider (LLM)
                                                                         ▼
                                                        tools.execute_tool  ← validation, account boundary, idempotency, fault injection
                                                                         │
                                         ┌───────────────┬───────────────┼───────────────┐
                                         ▼               ▼               ▼               ▼
                                     rules.py        retrieval.py     db.py (SQLite, in-memory, per session)
                                  (eligibility,     (TF-IDF over kb/)  accounts, journeys, interactions,
                                   transitions)                        tasks, runs, tool_executions, guard_log
```

## Data flow
1. A click calls a service. Rendering never calls one.
2. Inbound customer text is stored as untrusted data with keyword signals (`intent`). If it says the customer already tried the steps, the docs from the last agent message are recorded on the journey as attempted. The text itself is never executed or trusted for permissions.
3. `run_agent` creates a run, then loops: decider proposes a `Call`, the tool layer validates and executes it, the result goes back to the decider. The loop ends on `Finish`, an LLM error, or the step limit (default 10).
4. Every call is recorded in `tool_executions`; guard events (blocked sends, duplicates prevented, rejected overrides) go to `guard_log`.

## Agent and tools
Objective: *help eligible customers reach planned onboarding milestones using relevant guidance, while respecting preferences and escalating unresolved problems.*

| Tool | Reads/writes | Notes |
|---|---|---|
| get_customer_context | read | goal, plan, journeys, masked contact, **eligibility with reasons** |
| get_setup_progress | read | milestones from product events, data freshness |
| get_interaction_history | read | cross-channel messages, attempted/sent docs |
| search_documentation | read | TF-IDF; returns `supported` flag |
| check_support_cases | read | open cases and tasks |
| send_guidance | write | kinds: proactive, reply, status_update, confirmation; rules can refuse |
| pause_journey | write | cancels reminders; schedules resume check |
| resume_journey | write | only from paused or resolved-awaiting-check |
| create_handoff | write | creates case + task with full context; never duplicates |
| update_journey_status | write | completion requires fresh progress; opt-out cascades |

Inputs/outputs are Pydantic models (`extra="forbid"`). There is no free-form SQL or code execution anywhere.

## State model
Journey state is separate from milestone status (derived from product events).

```
monitoring ─► guidance_sent ─► waiting_for_customer ─┐
   │  ▲            │                  │              │
   │  └────────────┴──────────────────┘              │
   ├─► paused_until_rollout ◄──(pause_journey)───────┤
   ├─► waiting_for_human ─► resolved_awaiting_progress_check ─► monitoring / guidance_sent / waiting_for_customer
   └─► completed (terminal)      opted_out (terminal)  ◄── reachable from every non-terminal state
```
The full transition table is `TRANSITIONS` in `cso/models.py`; `set_journey_state` refuses anything else. `waiting_for_human` can also move to `completed` if fresh product events prove setup is done; any open task then stays for the operator to close.

## Business rules (code, not prompts)
`rules.evaluate_outreach` returns a list of named checks: missing data, opt-out, journey open, stale data, setup incomplete, rollout started, no blocking case, stalled for ≥ threshold, frequency limits, unanswered cap. `send_guidance` calls it before writing a message, so the same gate applies to scripted and live runs. Replies, status updates and opt-out confirmations use a smaller set (contact present, not opted out, journey open, unanswered inbound for replies).

## Account isolation
- Each Streamlit session builds its own in-memory SQLite database; nothing is shared across visitors.
- Within a session, a run is bound to one `account_id`. Any tool call naming another account is refused (`account_boundary`) and logged. Journey and contact IDs are checked to belong to that account.
- API keys live in the session or environment and never enter the database or UI.

## Failure handling
- A tool returns `ok=false` with a code; scripted flows and the live prompt both require message text to match the result (Check 08).
- Idempotency keys (`trigger|journey|tool|discriminator`) make retries safe; handoffs also dedupe on an open task.
- Live API errors become `outcome=error` on the run with a user-readable message. No scripted substitution.
- Step limit stops runaway loops.
- Unexpected exceptions inside tools return `internal_error` rather than crashing the session.

## Time
A demo clock replaces wall time. Advancing it runs a simulated sync that refreshes product data (except the one account seeded as stale). Scheduled actions run only when the user clicks **Run pending actions** or the daily scan.
