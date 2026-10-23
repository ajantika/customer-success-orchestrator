# Demo: Northstar Retail (Account Team), about five minutes

Setup: `streamlit run app.py`. On Overview choose **Start meeting preparation**. It resets the data and opens the Meeting preparation page with the meeting already selected. The sidebar badge says **Demo mode** (prepared rules, no AI model).

| Time | Do this | What it proves |
|---|---|---|
| 0:00 | Read the upcoming meetings list; note the selected Northstar meeting tomorrow | A simulated calendar with owner, solutions architect, purpose and lifecycle stage. No real calendar or CRM |
| 0:30 | Read the signals row under the meeting | Goal, setup progress, shared-workflow activity (0 in 14 days vs 9 before), intro training completed (6), next module (2) |
| 1:00 | Click **Prepare the brief** (guided bar) | The assistant gathers meeting, goal, usage, learning, blockers and catalog evidence, then saves one recommendation. Nothing is sent to the customer |
| 1:30 | Read the recommendation card | Next action phrased as a question; why now; customer goal; talking point; suggested free course with prerequisites; what to confirm; evidence with timestamps and "evidence completeness"; no confidence percentage |
| 2:30 | Click **Mark as reviewed**, then **Edit and accept** | Lifecycle moves Generated → Reviewed → Edited. Open "What changed" to see original vs current side by side; review history shows reviewer, time and note |
| 3:15 | Click **Mark as discussed** | "Discussed" is separate from anything the customer does |
| 3:30 | Click **Simulate enrolment** | Customer learning outcomes are tracked separately: accepting a recommendation never enrolled anyone |
| 4:00 | Open **Try other situations**, choose "A technical blocker is open", **Apply situation**, then **Prepare meeting brief** | The recommendation changes to technical follow-up first. Try "Prerequisites are not met", "The relevant course is already completed", "Learner information is missing", "Larger team: a paid workshop may fit", "A recommendation was already dismissed", "The meeting was cancelled" |
| 4:40 | **Feedback summary** | Dismissal reasons, edits, accepted-but-undiscussed and repeated gaps, for roadmap decisions. The assistant does not learn from them automatically |
| 5:00 | Evaluation → Observed in this session | Eligible meetings, briefs generated and viewed, reviews, decisions, discussed, learning updates, each with a denominator. Seeded history is labelled synthetic |

Optional: **Scan upcoming meetings** prepares briefs for every meeting in the next 7 days; running it twice creates no duplicates.
