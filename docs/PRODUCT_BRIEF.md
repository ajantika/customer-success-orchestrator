# Product brief

*Independent portfolio prototype. Fictional company, synthetic data.*

## Two user groups, one foundation
| Group | Goal | Workflow |
|---|---|---|
| **Customer admins** (the people receiving help) | Get set up on the products they bought, on their own schedule, without being spammed | Customer onboarding assistance |
| **Customer Success, Support** | Nudge the right customers at the right time; receive escalations with context | Onboarding assistance and the human work queue |
| **Account Executives and Solutions Architects** | Walk into a customer meeting knowing the goal, usage, learning status and the sensible next step | Account Team enablement |
| **Analytics / product owners** | See what is working and what reviewers reject | Evaluation page and feedback summary |

Both workflows read the same customer records, product events, support cases, documentation and rules.

## Problems
1. **Onboarding.** Customers adopt products on different schedules. Reminders ignore the customer's rollout plan, collide with open support issues, and handoffs to people lose context.
2. **Account Team.** Before a customer meeting, an AE or SA must piece together goals, usage, training status and open issues from separate tools. Training suggestions are easy to get wrong: recommending a course already completed, one whose prerequisites are unmet, or training when the real blocker is technical. Low usage is also not proof that people need training.

## Scope
In: onboarding milestones for Tasks, Docs, Support; one onboarding agent; simulated email and chat; documentation retrieval; human queue; configurable policy; a fictional training catalog; simulated upcoming meetings; briefs and recommendations with human review and feedback; evaluation views.
Out: renewals, billing, expansion selling, real message delivery, real calendar/CRM, real enrolment or purchases.

## Journey 1: Maple Design (onboarding)
Maple bought three products. Tasks is complete, Docs setup is stalled at the directory connection, Support rolls out later.
1. The agent detects stalled Docs setup and checks plan, progress, history, contact rules and cases. 2. It sends setup help (source cited). 3. The customer says "the directory connection is failing". 4. The error is unknown, so the agent asks one short question. 5. The customer says it is an authentication error. 6. The agent sends only the matching troubleshooting section. 7. The customer says they already tried it. 8. The agent records the attempted steps, creates one Technical Support handoff and pauses reminders. 9. A person resolves it with a note. 10. A fresh progress check runs; resolving the task does not complete onboarding. 11. When product events show setup done, pending reminders are cancelled and the journey completes. Support never receives outreach.

## Journey 2: Northstar Retail (Account Team)
Northstar wants a shared documentation workflow across several teams. A review meeting is tomorrow. Six employees finished introductory training, two finished the next module, adoption of the workflow has stalled, and no technical case is open.
1. The assistant reads the meeting and goal. 2. It checks usage, learning progress, blockers and rollout plans. 3. It checks the training catalog and prerequisites. 4. It saves a recommendation: *ask whether the team needs help applying the workflow; if a skills gap is confirmed, discuss the next module*, with evidence, unknowns and a talking point. 5. A reviewer accepts, edits, dismisses or defers it, with reasons. 6. After the meeting it is marked discussed. 7. Customer enrolment and completion are tracked separately and are never implied by acceptance.

## Requirements and acceptance
| # | Requirement | Verified by |
|---|---|---|
| R1 | No outreach before planned rollout | Check 01 |
| R2 | Never contact opted-out customers | Check 04 |
| R3 | Completed setup cancels reminders | Check 02 |
| R4 | No duplicate messages, handoffs or recommendations | Checks 03, 09, 10, 21 |
| R5 | Do not repeat tried guidance; ask before sending instructions when the error is unknown | Checks 05, 31 |
| R6 | Resolution forces a fresh progress check | Check 12 |
| R7 | A failed tool is never reported as success | Check 08 |
| R8 | Account isolation, including Account Team tools | Checks 13, 22 |
| R9 | Untrusted text cannot change policy | Check 14 |
| R10 | Cited documents must be the retrieved ones | Check 31, tool validation |
| R11 | No training recommended again, with unmet prerequisites, on stale or missing learner data, or during a technical blocker | Checks 16-19 |
| R12 | Dismissed and deferred recommendations respected; cancelled meetings stop prompts | Checks 20, 26, 32 |
| R13 | Accepting a recommendation never enrols anyone | Check 24 |
| R14 | Edits keep the original | Check 25 |
| R15 | Recommendations cite only gathered evidence; paid options need a justification | Checks 23, 27, 28 |
| R16 | Selection and navigation are stable; guided demos open the right customer and task | UI tests |

## Future extensions
Real channels and calendar/CRM integration, embedding retrieval, a learned intent classifier, per-segment policies, a pilot with a holdout group, SLAs for handoffs, and a reviewed content-gap backlog driven by feedback.
