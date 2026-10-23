# Usability review (self-service)

*Reviewed on the `account-team-enablement` branch, run locally. I am the developer and tested as a first-time visitor would, following only on-screen instructions. No independent user took part, so this is **not** first-time-user validation.*

## What a visitor sees
1. **First screen** states what the product does, who uses it and offers two entry points with duration and the role they play: *Try customer onboarding* (about 5 minutes) and *Prepare for a customer meeting* (about 4 minutes). No login, key or setup. A "How to use this demo" guide is on the page and in the sidebar.
2. **Each walkthrough** opens the correct customer, shows "The situation" (2-3 sentences), a progress bar, one highlighted next action and a banner that says who the visitor is playing.
3. **Every action** shows *What just happened*: what the system found, what it did, why, and what to do next. Tool calls, inputs and evidence are in expanders.
4. **Roles** are labelled on every step: replying as the customer, acting as the support specialist, acting as the Account Team, watching the assistant work.
5. **Account Team brief** shows goal, signals, suggested next step, talking point, sources and unknowns; a legend explains Accept / Edit / Dismiss / Defer / Mark discussed; each action says where it was recorded and that nothing is sent or enrolled.
6. **Endings** show a summary: the original problem, actions taken, resulting state and remaining follow-up, then next steps (explore the other workflow, view activity and evaluation, restart). Success is stated only when verified (onboarding: product events show setup complete; Account Team: the recommendation was discussed, with learning outcomes stated as synthetic and effect unknown).
7. **Recovery:** *Restart this walkthrough* (resets only that customer, with the consequences stated), *Back to overview*, *Continue where you left off* / *Start over* on the Overview, *Reset all demo data*, and a failed step shows an error card with a way forward.

## Paths I tested
| Path | How | Result |
|---|---|---|
| Customer onboarding, start to finish, laptop width (1280 px) | In the browser by clicking only the highlighted buttons, typing the resolution note, and following the on-screen next steps | Completed; summary shown; Docs journey completed from product events |
| Meeting preparation, start to finish, laptop width | Same, in the browser | Completed; recommendation discussed; learning outcome shown as synthetic |
| Narrow screen (390 px) | Browser screenshots of the Overview and the Meeting preparation page | Text readable, buttons full width, no horizontal scrolling seen on those screens |
| Both workflows via automated clicks | `tests/test_ui.py` (17 tests) | Pass: selection survives actions and navigation, handoff link opens the exact task, restart resets only one customer, failed handoff reported honestly and retried, role labels present |
| Rules and tools | `tests/test_workflows.py` (40 tests) and `python -m cso.evaluation` | 34 of 34 workflow checks pass |

## Limits
- Tested by the developer, not an independent visitor. A real first-time-user test could still find confusing wording.
- Browser checks covered the Overview, Customer onboarding, Support tasks and Meeting preparation pages. I did not click through every page of the app on a narrow screen (Customer workspace, Journey configuration and Evaluation were only checked on laptop width through automated tests and text review).
- Refreshing the browser tab starts a new demo (the guide says so).
- Live AI mode was not exercised against a real model.
- No screen-reader or colour-contrast audit was done.
