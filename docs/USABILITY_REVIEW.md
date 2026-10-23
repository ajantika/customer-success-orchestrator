# Usability review (self-service)

*Reviewed on the `account-team-enablement` branch, run locally. I am the developer and tested as a first-time visitor would, following only on-screen instructions. No independent user took part, so this is **not** first-time-user validation.*

## What a visitor sees
1. **First screen** states what the product does, who uses it and offers two entry points with duration and the role they play: *Try customer onboarding* (about 5 minutes) and *Prepare for a customer meeting* (about 4 minutes). No login, key or setup. A "How to use this demo" guide is on the page and in the sidebar.
2. **Each walkthrough** opens the correct customer, shows "The situation" (2-3 sentences), a progress bar, one highlighted next action and a banner that says who the visitor is playing.
3. **Every action** shows *What just happened*: what the system found, what it did, why, and what to do next. Tool calls, inputs and evidence are in expanders.
4. **Plain wording:** the interface avoids job titles and customer-success terms; instructions are ordinary text, and only buttons look clickable.
5. **Account Team brief** shows goal, signals, suggested next step, talking point, sources and unknowns; a legend explains Accept / Edit / Dismiss / Defer / Mark discussed; each action says where it was recorded and that nothing is sent or enrolled.
6. **Endings** show a summary: the original problem, actions taken, resulting state and remaining follow-up, then next steps (explore the other workflow, view activity and evaluation, restart). Success is stated only when verified (onboarding: product events show setup complete; Account Team: the recommendation was discussed, with learning outcomes stated as synthetic and effect unknown).
7. **Recovery:** *Restart this walkthrough* (resets only that customer, with the consequences stated), *Back to overview*, *Continue where you left off* / *Start over* on the Overview, *Reset all demo data*, and a failed step shows an error card with a way forward.

## Paths I tested
| Path | How | Result |
|---|---|---|
| Customer onboarding, start to finish, laptop width (1280 px) | In the browser by clicking only the highlighted buttons, typing the resolution note, and following the on-screen next steps | Completed; summary shown; Docs journey completed from product events |
| Meeting preparation, start to finish, laptop width | Same, in the browser | Completed; recommendation discussed; learning outcome shown as synthetic |
| Both workflows via automated clicks | `tests/test_ui.py` (17 tests) | Pass: selection survives actions and navigation, handoff link opens the exact task, restart resets only one customer, failed handoff reported honestly and retried, role labels present |
| Rules and tools | `tests/test_workflows.py` (40 tests) and `python -m cso.evaluation` | 34 of 34 workflow checks pass |

## Limits
- Tested by the developer, not an independent visitor. A real first-time-user test could still find confusing wording.
- The interface targets laptop and desktop screens. Narrow screens were glanced at once but are not a goal for this version.
- Refreshing the browser tab starts a new demo (the guide says so).
- Live AI mode was not exercised against a real model.
- No screen-reader or colour-contrast audit was done.

## Changes after the first review round
- "Edit and accept" now records the edit and the acceptance as separate history entries, and the status reads "Accepted with edits".
- The review message follows the recommendation's status (Review required, Accepted, Discussed, Dismissed, Withdrawn).
- Talking points are written as something a salesperson would say to the customer; the usage and learning analysis stays in the internal brief.
- The meeting page's main view holds the goal, why attention is needed, the recommended action, the talking point and the review buttons. Signals, training options, unknowns, evidence and history are in expanders.
- Simulated completion is described precisely: the demo button creates sample product events. A typed completion claim without events keeps the journey open (workflow check 35 and a UI test).
- Resolving a support task is one form with "Save note and resolve".
- Scope for this version: the model-backed option, situation scenarios, the demo clock, handoff-failure switch and the configuration page are hidden unless `CSO_ADVANCED=1`.

## Changes after the second review round (plain-language pass)
- New homepage introduction and a discreet "Interactive demo · Uses sample data and prepared responses." line; the long list of job titles is gone, and the fuller explanation of prepared scenarios and rules is under "About this demo".
- Two simpler cards ("Help a customer get started" / "Prepare for a customer conversation") with the approximate duration.
- Job titles and role announcements ("You are acting as…") removed from the walkthroughs. Instructions are plain text; one filled button per step.
- **Reply buttons:** I tested every reply control. They all worked (each click added the customer message and the assistant's response). The confusion was visibility: new messages sat at the bottom of a scrolling box, and the guided button was labelled "Send this reply" beneath a separate sentence. The conversation is now newest first, the reply itself is the button label, and a short result message plus a toast confirms each click.
- The final onboarding step is "Simulate completed setup" with helper text; a typed completion claim creates no events (workflow check 35 and a UI test).
- Support tasks show the problem, what was tried and who owns the next step; resolving uses the single "Save note and resolve" form and says: "The support issue is resolved. The assistant will now check whether the customer has completed setup."
- One short result message after each action, with "what happened and why" in a Details section.
