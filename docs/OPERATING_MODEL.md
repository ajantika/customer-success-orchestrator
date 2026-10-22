# Operating model (proposal)

*A proposal for how teams could run a system like this. Nothing here describes an actual organisation.*

## Responsibilities
| Team | Owns | Does not own |
|---|---|---|
| **Customer Success** | Journey design: milestones, goals, stall thresholds, message content standards, who gets contacted; the decision log | Data pipelines, model internals |
| **Support** | The handoff queue: triage, SLAs, resolution notes, feedback on what context was missing; troubleshooting documentation accuracy | Journey thresholds |
| **Engineering (incl. data and AI)** | Event pipelines and data quality, tool/API contracts, agent runtime, retrieval, safety guards, logging, deployment | Customer-facing policy decisions |
| **Analytics** | Metric definitions, experiment design, cohort analysis, evaluation set and human-rating process, reporting | Writing journey rules |
| **Privacy / Legal (consulted)** | Consent and contact governance, opt-out handling, retention | Day-to-day tuning |

## Dependencies
- Product events must arrive with timestamps and a freshness signal, or the agent should stay silent.
- Documentation owners keep troubleshooting and limitation pages current; stale docs are the main grounding risk.
- Support routing rules (team per issue category) must be kept in sync with the configuration page.

## Escalation ownership
- Integration and configuration problems: **Technical Support** (configurable).
- Goal, rollout or training questions, documentation gaps: **Customer Success**.
- If ownership is unclear, the journey owner (Customer Success) is the accountable DRI until reassigned, and the decision log records why.
- Agent safety issues (wrong claim, contact after opt-out): Engineering on-call, with Customer Success informed.

## Reviewing proposed changes
1. Propose in the decision log: change, reason, expected effect, rollback.
2. Preview on the configuration page's example accounts; run the 15 workflow checks.
3. Analytics reviews measurement impact (does it change a metric's denominator?).
4. Support reviews anything that changes escalation volume.
5. Roll out to a small cohort with a comparison group; review guardrail metrics (opt-outs, complaints, duplicate sends) before widening.
6. Architecture principles are not reopened without a stated rationale and a new decision-log entry.

## Cadence
Weekly operating review (handoff volume, tool errors, blocked-send reasons, opt-outs); monthly rating session on a sample of agent messages; quarterly threshold review.
