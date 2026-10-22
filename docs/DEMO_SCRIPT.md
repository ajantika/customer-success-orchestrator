# Five-minute demo: Maple Design

Setup: `streamlit run app.py`, Scripted demo mode (default). Keep the **Agent workspace** activity panel visible; it is the proof at each step.

| Time | Do this | What it proves |
|---|---|---|
| 0:00 | **Overview.** Read the one-line description, point at the KPIs, click **Start guided demo** | Starts from clean seeded state; Maple Design is selected; a checklist appears on the Agent workspace |
| 0:30 | **Customer workspace.** Maple: Docs shows 1 of 4 milestones, expand "Not eligible/Eligible for outreach — why?". Note Support is "Paused until rollout" (plans start in about 6 weeks) and Tasks is Completed | The agent respects the *customer's* rollout plan; eligibility is explainable and rule-based |
| 1:00 | **Agent workspace → Run onboarding check** (guided step 1) | One stalled-Docs signal becomes a message in the simulated inbox with a source (open **Sources**). Activity panel lists the tools: context, progress, history, cases, search, send, status update |
| 1:30 | Click **Run onboarding check** again | Nothing new is sent: the activity panel says why (frequency limit). Reruns and repeat triggers don't duplicate messages |
| 1:45 | Click **The directory connection is failing.** | The agent retrieves troubleshooting docs it hasn't already sent (DOC-105) and replies with cited sources |
| 2:15 | Click **We already tried those instructions.** | The attempted steps are recorded; one handoff is created for Technical Support; reminders are paused; the journey is **Waiting for human**; the reply names the task ID. *Optional:* tick **Simulate handoff failure** first to see the agent admit nothing was created, then untick |
| 3:00 | **Human work queue.** Open the new task: goal, product status, guidance sent, attempted steps, conversation refs. Assign it. Type a resolution note, leave the simulate-fix box ticked, click **Resolve task** | Context travels with the handoff; a note is required; the banner says *support resolved is not onboarding complete* |
| 3:40 | Back on **Agent workspace**, open the latest run | Resolution triggered a **fresh progress check** (progress_check run): journey resumed, customer updated with the next milestone, new reminder scheduled |
| 4:10 | Click **Setup is now complete.** | Real synthetic product events are generated, the agent verifies them, pending reminders are cancelled and the journey becomes **Completed** |
| 4:40 | **Evaluation → Run 15 workflow checks**; glance at the three tabs | Observed session activity, seeded history and tests are kept separate; denominators are shown; seeded numbers are labelled synthetic |
| 5:00 | *(Optional)* **Overview → Run daily scan** | The same rules at scale: future rollouts, healthy progress, frequency limits, opt-outs and missing data produce no messages |

Edge cases worth one sentence each (Agent workspace → example picker): the quantum-ledger question (unsupported docs → honest fallback), and the "ignore your previous instructions" message (rejected; no tools beyond a safe reply).
