# Customer Success Orchestrator

> **Independent portfolio prototype • Synthetic customer data.** Not affiliated with any company. Every customer, event and metric is generated.

**Live demo: https://customer-success-orchestrator.streamlit.app/**

A working prototype of an agentic customer-success platform for a fictional SaaS company with three products: Tasks, Docs and Support. It shows how product signals become **personalised guidance, agent actions and human handoffs**, with business rules enforced in application code rather than left to a model.

One onboarding agent runs a bounded loop over ten validated tools. Tools really change state: they write messages to a simulated inbox, create human tasks, pause journeys and cancel reminders. Retries and Streamlit reruns cannot duplicate them.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

No API key is needed. The app starts in **Scripted demo** mode. On the Overview page click **Start guided demo** and follow the checklist (the full walkthrough is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)).

Run the checks:

```bash
pytest                       # workflow checks, tool/rule tests, UI click-through, live-adapter tests with a fake client
python -m cso.evaluation     # the 15 workflow checks with per-check evidence
```

## Modes

| | Scripted demo (default) | Live AI |
|---|---|---|
| Decisions | Deterministic rules in `cso/agent.py` (**not** an LLM; labelled as such everywhere) | A model chooses tools via the Anthropic Messages API (`cso/llm.py`) |
| Tools, rules, state | Identical | Identical |
| Needs a key | No | Yes |
| On failure | n/a | Shows the error, keeps your session, never falls back silently to scripted output |

**Enable Live AI** with any one of:

- `export ANTHROPIC_API_KEY=...` before `streamlit run app.py`
- `.streamlit/secrets.toml` containing `ANTHROPIC_API_KEY = "..."` (see `.streamlit/secrets.toml.example`; the real file is git-ignored)
- Paste a key in the sidebar (kept in that browser session's memory only)

Then choose **Live AI** in the sidebar. Optional: `CSO_MODEL` overrides the default model (`claude-sonnet-5-5`). Keys are never displayed or written to the database.

> The live path is covered by tests that use a fake provider client. It has **not** been exercised against the real API in this repository's verification, so treat real-model behaviour as unvalidated.

## What's in the app

| Page | Purpose |
|---|---|
| Overview | KPIs, prioritised accounts with reasons, **Start guided demo**, a daily scan that shows rules holding back outreach at scale |
| Customer workspace | Goal, products, rollout plan, milestones, usage, open issues, contact preferences, unified timeline, and *why* a customer is or isn't eligible |
| Agent workspace | Simulated inbox (email/chat), six scenario buttons, free-text replies, agent activity panel (signal, evidence, tools, action, result, next step), demo clock controls |
| Human work queue | Assign, update and resolve handoffs; resolution note required; "task resolved" is kept distinct from "onboarding complete" |
| Journey configuration | Eligibility, stall threshold, frequency, stopping and escalation rules, team ownership, milestone definitions; previews effect on an example account |
| Evaluation | Observed session activity vs seeded synthetic history vs agent evaluation (workflow checks, human ratings), with definitions and denominators |

## Project structure

```
app.py                  Streamlit entry point, navigation, sidebar controls
cso/
  models.py             Journey states, allowed transitions, validated Settings
  db.py                 Session-scoped in-memory SQLite repository
  datagen.py            Deterministic synthetic data (40 accounts)
  rules.py              Business rules: eligibility, progress, opt-out, message screening
  tools.py              10 tools: schemas, account boundary, idempotency, failures
  retrieval.py          TF-IDF documentation retriever
  agent.py              Bounded agent loop + scripted decider
  llm.py                Live AI decider (Anthropic adapter)
  services.py           Entry points for side effects (button callbacks only)
  evaluation.py         15 workflow checks, human ratings, optional live runner
  ui/                   One module per page + shared styling
kb/                     Fictional product docs (Markdown, stable IDs)
tests/                  pytest suite
docs/                   Product brief, architecture, decisions, operating model, evaluation, case study, demo script
```

## Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. In Streamlit Community Cloud choose **New app**, select the repo, branch, and main file `app.py`.
3. Optional: under **Advanced settings → Secrets** add `ANTHROPIC_API_KEY = "..."` to make Live AI available. Anyone using the public URL could then spend that key's budget, so leave it out for a public demo and let visitors paste their own key.

Each visitor gets a private in-memory database. Their changes are invisible to others and are lost when the session ends.

## Known limitations

- Email and chat are simulated; nothing is sent anywhere.
- Reply understanding in Scripted mode is a keyword screen, so paraphrases may be classified as "unknown". The agent then searches the docs or offers a handoff.
- Retrieval is section-level TF-IDF (no embeddings), so it misses synonyms. An unsupported question triggers a documented fallback.
- No scheduler: reminders run when you click **Run pending actions** or the daily scan, using a controllable demo clock.
- Thresholds (stall days, frequency, stale data) are demo policy, not benchmarks.
- Seeded metrics are synthetic and imply nothing about real improvement.
- Only onboarding and adoption are in scope: no renewals, billing or expansion. The agent cannot change billing, plans or permissions.
- Live AI mode is untested against a real model here (see above).

## Documentation

[Product brief](docs/PRODUCT_BRIEF.md) · [Architecture](docs/ARCHITECTURE.md) · [Decisions](docs/DECISIONS.md) · [Operating model](docs/OPERATING_MODEL.md) · [Evaluation](docs/EVALUATION.md) · [Case study](docs/PORTFOLIO_CASE_STUDY.md) · [Demo script](docs/DEMO_SCRIPT.md)
