# Demo: Maple Design (customer onboarding), about five minutes

Setup: `streamlit run app.py`. The sidebar badge says **Demo mode** (no AI model is called). On Overview choose **Explore setup support**.

| Time | Do this | What it proves |
|---|---|---|
| 0:00 | Overview: read the two entry points and the counts, then click **Explore setup support** | Opens Maple's Setup support page with a guided bar ("Step 1 of 6") and the customer already selected |
| 0:30 | Customer workspace (sidebar): open "Why eligible?" for Docs | Eligibility is explainable and based on the customer's own plan. Support shows "Paused until rollout" |
| 1:00 | Setup support page → **Check Maple's setup** | Stalled Docs setup becomes a message with a cited source. Open **What the agent did** to see what it noticed and checked. The customer selection stays put |
| 1:30 | *Optional:* **Leave the guided demo**, click **Run onboarding check** again, then reopen the guided demo from Overview only if you want a clean run | Nothing new is sent (frequency limit). Reruns never duplicate |
| 1:45 | Click the reply **The directory connection is failing.** | The error is unknown, so the agent asks one short question instead of sending every fix |
| 2:15 | Click the reply **We see an authentication error.** | Only the matching troubleshooting section is sent; its document and section open from the Source expander |
| 2:45 | Click the reply **We already tried those steps.** | Attempted steps recorded; one Technical Support handoff created; reminders paused; journey is "Waiting for human". *Reviewer option (`CSO_ADVANCED=1`):* the Simulate handoff failure switch shows the assistant saying nothing was created |
| 3:15 | **Open the support task** | Queue opens on Maple's exact task, with goal, product status, guidance sent and attempted steps. Assign it, write a note, **Save note and resolve** |
| 4:00 | **Return to this customer's journey**, open **What the agent did** | Resolution triggered a fresh progress check; the customer got a status update with the next milestone. Resolving did not complete onboarding |
| 4:30 | Click **Simulate completed setup** | The button adds sample product events; the agent verifies them, cancels reminders and completes the journey. Support never received outreach |
| 5:00 | Evaluation → Observed in this session | Tool calls split into successes, expected policy blocks, technical failures and duplicates prevented, with denominators |

Edge cases (Setup support page → "Reply as the customer" → example): the unsupported question gets an honest fallback; the "ignore your previous instructions" message is rejected.
