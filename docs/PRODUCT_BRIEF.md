# Product brief

*Independent portfolio prototype. Fictional company, synthetic data.*

## Customer problem
Customers who buy several products rarely adopt them all at once. Teams see stalled setup in usage data but struggle to act: signals are scattered (product events, rollout plans, support cases, past conversations), outreach can collide with an open support issue, and when an agent or bot can't help, the human who picks it up starts from zero. Result: well-meant reminders arrive at the wrong time, customers repeat themselves, and nobody owns the gap.

## Target users
- **Customer Success managers**: want the right customers nudged at the right time, without spamming.
- **Support engineers**: want escalations that arrive with goal, history and attempted steps.
- **Customer admins** (the persona receiving messages): want relevant help, respect for their rollout plan and an easy way to stop messages.
- **Operations / analytics**: want transparent rules and measurable behaviour.

## Goals
1. Detect stalled onboarding against the customer's *own planned rollout*.
2. Give specific, source-backed guidance for the next milestone.
3. Interpret replies and act: answer, pause, escalate, complete or stop.
4. Hand off to humans with full context and prevent conflicting automation meanwhile.
5. Make every decision inspectable: tools called, evidence, outcome.

## Scope (v1: onboarding and adoption only)
In: onboarding milestones for Tasks, Docs, Support; one agent with ten tools; simulated email/chat; documentation retrieval; human queue; configurable policy; evaluation views.
Out: renewals, billing automation, expansion sales, real message delivery, production integrations.

## Primary journey: Maple Design
Maple bought all three products. Tasks is active, Docs rollout is planned for now but setup is stalled at the directory integration, Support is planned for later.
1. System detects stalled Docs setup. 2. Agent checks plan, progress, history, contact eligibility, cases. 3. Docs outreach is appropriate. 4. Guidance goes to the admin's simulated inbox. 5. Customer reports trouble connecting the directory. 6. Agent retrieves troubleshooting docs and replies with sources. 7. Customer says they already tried those steps. 8. Agent records the attempted steps, creates one technical-support handoff and pauses reminders. 9. Operator resolves the task with a note. 10. System re-checks fresh progress before deciding. 11. When setup completes, pending reminders are cancelled. 12. Journey advances to the next milestone or completes. Throughout, Support (rollout later) gets no outreach.

## Requirements and acceptance criteria
| # | Requirement | Acceptance |
|---|---|---|
| R1 | No outreach before planned rollout unless the customer asks for help | Check 01 passes; Maple's Support journey receives nothing |
| R2 | Never contact opted-out customers | Check 04 |
| R3 | No reminders after setup is complete; cancel pending ones | Check 02 |
| R4 | No conflicting reminders while a blocking case is open | Eligibility check `no_blocking_case` |
| R5 | Don't repeat guidance the customer already tried | Check 05 |
| R6 | No duplicate handoffs or messages on retries/reruns | Checks 03, 09, 10; UI rerun test |
| R7 | Human resolution triggers a fresh progress check | Check 12 |
| R8 | A failed tool is never reported as success | Check 08 |
| R9 | Account isolation | Check 13 |
| R10 | Untrusted text can't change policy | Check 14 |
| R11 | Frequency limits and stale/missing data respected | Checks 11, 15 |
| R12 | Scripted mode needs no key and is clearly labelled; Live AI uses identical tools | Mode label on every page; adapter tests |

## Future extensions
Real email/chat channels and consent management; embedding retrieval; learned intent classification; per-segment policies; a pilot with a randomised holdout; analytics on agent effectiveness; richer handoff routing and SLAs.
