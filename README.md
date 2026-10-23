# Customer Success Orchestrator

> **Independent portfolio prototype • Synthetic customer data.** Not affiliated with any company. Every customer, course, event and metric is generated.

Two connected workflows on one customer-intelligence foundation, for a fictional SaaS company with three products (Tasks, Docs, Support):

1. **Customer onboarding assistance.** Detect stalled setup, give guidance grounded in documentation, understand replies, hand off to a person when needed, and verify progress.
2. **Account Team enablement.** Help an Account Executive or Solutions Architect prepare for a customer meeting: goal, usage, learning progress, support status and relevant training, turned into a brief, a recommendation with evidence, and a human review step.

Business rules (who may be contacted, when, how often, which tools an agent may call, what counts as evidence) are enforced in application code, not left to a model.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

No API key is needed. The app starts in **Demo mode**. On the Overview page choose **Start customer onboarding** or **Start meeting preparation**. Each opens a short guided checklist. The app guides you; written walkthroughs: [Maple Design](docs/DEMO_SCRIPT_MAPLE.md) and [Northstar Retail](docs/DEMO_SCRIPT_NORTHSTAR.md).

```bash
pytest                       # workflow checks, tool/rule tests, UI click-through tests, live-adapter tests with a fake client
python -m cso.evaluation     # the 34 workflow checks with per-check evidence
```

## Demo mode and Live AI

| | Demo mode (default) | Live AI |
|---|---|---|
| Decisions | Prepared scenarios and deterministic rules in `cso/agent.py`. **No AI model is called.** | A model chooses tools and writes messages and talking points (`cso/llm.py`, Anthropic Messages API) |
| Tools, rules, state, review steps | Identical | Identical |
| Needs a key | No | Yes |
| On failure | n/a | Shows the error and keeps your session. Never falls back silently to prepared output |

An always-visible badge in the sidebar shows the current mode. To try an AI model open **Try with an AI model** in the sidebar and tick the box. Provide a key by any one of:

- `export ANTHROPIC_API_KEY=...` before `streamlit run app.py`
- `.streamlit/secrets.toml` with `ANTHROPIC_API_KEY = "..."` (see `.streamlit/secrets.toml.example`; the real file is git-ignored)
- paste a key into the sidebar box (kept in that browser session's memory only)

Optional: `CSO_MODEL` or the sidebar "Model" box overrides the default model (`claude-sonnet-5-5`). Keys are never displayed, logged or written to the database.

The model performs two jobs: it picks which permitted tool to call next and writes the customer message (onboarding) or the brief and talking points (Account Team). Validation, account boundaries, tool allow-lists, citation checks and review requirements run in code either way.

> The live path is covered by tests that use a fake provider client. It has **not** been run against a real model in this repository, so real-model behaviour is unvalidated.

## Pages

| Page | Purpose |
|---|---|
| Overview | Two entry points, account and journey counts (with definitions), accounts needing attention, daily scan |
| Customer workspace | Goal, lifecycle stage, owner, products and rollout plan, milestones, learning progress, upcoming meetings, open issues, contact preferences, timeline, and *why* a customer is or isn't eligible for outreach |
| Customer onboarding | Guided walkthrough with Maple Design: inbox, customer replies, a plain-language "What just happened" card after every action, technical details in an expander |
| Support tasks | You act as the support specialist: assign, update and resolve handoffs with a required note; opens on the exact task you came from |
| **Meeting preparation** (Account Team Assistant) | Simulated upcoming meetings, meeting brief, recommendation card with evidence, accept / edit / dismiss / defer / mark discussed, learning outcomes tracked separately, scenario controls, feedback summary |
| Journey configuration | Eligibility, thresholds, frequency, stopping and escalation rules, team ownership, milestone definitions |
| Evaluation | Observed session activity, seeded synthetic history, and system evaluation (workflow checks, human ratings), with definitions and denominators |

## Project structure

```
app.py                  Entry point, navigation, sidebar (mode badge, AI model settings, demo clock)
cso/
  models.py             Journey states and transitions, validated policy settings, milestone definitions
  db.py                 Session-scoped in-memory SQLite repository and schema
  datagen.py            Deterministic synthetic data (43 accounts)
  seed_team.py          Course catalog, Northstar Retail, prospects, meetings, recommendation history
  rules.py              Business rules: eligibility, progress, opt-out, message screening
  tools.py              16 tools: schemas, account boundary, allow-lists, idempotency, evidence, citations
  retrieval.py          TF-IDF documentation retriever
  agent.py              Bounded agent loop + deterministic decider (onboarding and meeting preparation)
  llm.py                Live AI decider (Anthropic adapter) with separate prompts per workflow
  services.py           Onboarding actions (button callbacks only)
  team.py               Account Team actions: prepare, scan, review, scenarios, measures
  evaluation.py         34 workflow checks, human ratings, optional live runner
  session.py            Canonical selection, navigation requests, mode
  ui/                   One module per page + styling
kb/                     Fictional product docs and learning paths (Markdown, stable IDs)
tests/                  pytest suite
docs/                   Brief, architecture, decisions, operating model, evaluation, case study, two demo scripts
```

## Deploy to Streamlit Community Cloud

1. Push to GitHub. 2. In Streamlit Community Cloud choose **Create app**, pick the repo and branch, main file `app.py`. 3. Leave secrets empty for a public demo; visitors can paste their own key. Each visitor gets a private in-memory database that resets when their session ends.

## Known limitations

- Email, chat, calendar and CRM are simulated. Nothing is sent, scheduled, enrolled or purchased.
- Reply understanding in Demo mode is a keyword screen, so paraphrases may land as "unknown"; the agent then searches docs or offers a handoff.
- Retrieval and training-catalog search are simple word-matching (TF-IDF / token overlap), with no synonyms.
- No scheduler: reminders and scans run when you click. Thresholds are demo policy, not benchmarks.
- Seeded metrics are synthetic and imply nothing about real improvement. Time saved, learning lift and revenue are not measured.
- Only onboarding, adoption and learning are in scope. The agent cannot change billing, plans or permissions.
- The Account Team assistant's feedback summary informs roadmap decisions; the assistant does not learn from feedback automatically.
- Live AI mode is untested against a real model (see above).

## Self-service use

The app is designed so a first-time visitor needs no explanation. The Overview states the purpose, users and the two workflows; each walkthrough opens the right customer, explains the situation in a few sentences, shows progress and one highlighted next action, and names the role you are playing at every step ("You are replying as the customer", "acting as the support specialist", "acting as the Account Team"). Every action produces a *What just happened* card (what was found, what was done, why, what to do next). Each walkthrough ends with a summary and next steps. **Restart this walkthrough** resets only that customer; **Back to overview** leaves the walkthrough; **Reset all demo data** (sidebar) resets everything. Details of what was tested are in [docs/USABILITY_REVIEW.md](docs/USABILITY_REVIEW.md).
