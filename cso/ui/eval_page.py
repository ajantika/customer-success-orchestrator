from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import evaluation as E, services as S, session
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import style


def _run_checks(db):
    res = E.run_workflow_checks()
    E.record_results(db, res)
    session.flash("success" if all(r["passed"] for r in res) else "warning", f"Ran {len(res)} workflow checks: {sum(r['passed'] for r in res)} passed.")


def _rate(db):
    ss = st.session_state
    try:
        E.save_rating(db, ss["rate_msg"], {k: ss[f"rate_{k}"] for k in E.CRITERIA}, ss.get("rate_note", ""))
        session.flash("success", f"Rating saved for {ss['rate_msg']}.")
    except ValueError as e:
        session.flash("warning", str(e))


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Evaluation and outcomes")
    st.caption("Three separate views. Nothing here is a measured business result: all customers and history are synthetic.")
    t1, t2, t3 = st.tabs(["1 · Observed in this demo session", "2 · Seeded synthetic history", "3 · Agent evaluation"])
    with t1:
        m = S.session_metrics(db)
        st.info("Counts only what happened in **your current session**. They reset with the demo and are not outcomes.")
        rows = [
            ("Agent runs", m["runs"], "Agent loop executions started in this session.", "n/a (count)"),
            ("Messages sent by the agent", m["agent_messages"], "Messages written to the simulated inbox.", "n/a (count)"),
            ("Customer replies", m["customer_messages"], "Inbound simulated messages.", "n/a (count)"),
            ("Tool calls / tool errors", f"{m['tool_calls']} / {m['tool_errors']}", "Errors include expected policy refusals (e.g. policy_blocked).", f"{m['tool_errors']} of {m['tool_calls']}"),
            ("Duplicate actions prevented", m["duplicates_prevented"], "Repeated idempotency keys or an already-open handoff.", "n/a (count)"),
            ("Unnecessary outreach prevented", m["outreach_prevented"], "Proactive runs that ended without a message because a rule said no, plus blocked sends and repeats of tried guidance.", "Proactive checks + blocked sends"),
            ("Policy-override messages rejected", m["policy_overrides"], "Customer messages matching override patterns.", "n/a (count)"),
            ("Human handoffs created / resolved", f"{m['handoffs_created']} / {m['handoffs_resolved']}", "Tasks created in this session.", "n/a (count)"),
            ("Journeys completed this session", f"{m['journeys_completed']} of {m['open_at_start']}", "Journeys that reached Completed after the session began.", f"{m['open_at_start']} journeys open at start"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Metric", "Value", "Definition", "Denominator"]), hide_index=True, width="stretch")
        if m["error_codes"]:
            st.markdown("**Tool error codes**")
            st.dataframe(pd.DataFrame(m["error_codes"]).rename(columns={"error": "Code", "n": "Count"}), hide_index=True)
        if not m["runs"]:
            st.caption("No activity yet. Use the guided demo from the Overview page.")
    with t2:
        sd = S.seeded_metrics(db)
        st.warning("**Synthetic.** Generated from a fixed random seed. Not real customers and not evidence of any improvement.")
        comp = pd.DataFrame([{"Product": PRODUCT_LABEL[r["product"]], "Rollout started": r["rollout_started"], "Completed": r["completed"],
                              "Setup completion": S.pct(r["completed"], r["rollout_started"])} for r in sd["completion"]])
        st.markdown("**Setup completion** — journeys completed ÷ journeys whose planned rollout had started at seed time")
        st.dataframe(comp, hide_index=True, width="stretch")
        st.markdown("**Time from onboarding start to first meaningful milestone** — median days from planned rollout start to first milestone event, accounts with ≥1 milestone only")
        st.dataframe(pd.DataFrame([{"Product": PRODUCT_LABEL[r["product"]], "Accounts (denominator)": r["accounts"], "Median days": r["median_days"] if r["median_days"] is not None else "n/a"} for r in sd["time_to_first"]]),
                     hide_index=True, width="stretch")
        st.markdown("**Seeded human handoffs**")
        st.dataframe(pd.DataFrame(sd["handoffs"]).rename(columns={"team": "Team", "status": "Status", "n": "Tasks"}), hide_index=True)
        flat = [{"Product": PRODUCT_LABEL[p], "State": STATE_LABEL[s], "Journeys": n} for p, d in sd["states"].items() for s, n in d.items()]
        fig = px.bar(pd.DataFrame(flat), x="Journeys", y="State", color="Product", orientation="h", title="Seeded journey outcomes by state (synthetic)",
                     color_discrete_sequence=["#3b4cca", "#0f766e", "#b45309"])
        fig.update_layout(height=360, margin=dict(l=0, r=0, t=40, b=0), yaxis=dict(categoryorder="total ascending"))
        st.plotly_chart(fig, width="stretch")
        with st.expander("How a production pilot could measure impact"):
            st.markdown("Seeded numbers cannot show that the agent changes outcomes. A pilot would randomly assign comparable eligible accounts to **agent-assisted** "
                        "and **business-as-usual** groups (or use a holdout), pre-register the primary metric (for example, share reaching the first milestone within 30 days), "
                        "compare groups over the same period with the same denominator rules, and review unsubscribe, complaint and escalation rates as guardrails. "
                        "Without randomisation, results would be confounded by account size, intent and seasonality.")
    with t3:
        st.markdown("#### Workflow checks (deterministic)")
        st.caption("These test application behaviour — rules, tools, state and idempotency — each on a fresh seeded database. They are **not** a language-quality evaluation.")
        st.button("Run 15 workflow checks", type="primary", on_click=_run_checks, args=(db,))
        res = db.q("SELECT * FROM eval_results WHERE suite='workflow' ORDER BY id")
        if res:
            st.markdown(f"**Last run:** {sum(r['passed'] for r in res)} of {len(res)} passed · {res[0]['ran_at'][:19].replace('T', ' ')}")
            st.dataframe(pd.DataFrame([{"Check": r["name"], "Result": "PASS" if r["passed"] else "FAIL", "Evidence": r["detail"][:260]} for r in res]), hide_index=True, width="stretch")
        else:
            st.markdown("**Not evaluated** in this session yet. The same checks run with `pytest`; see EVALUATION.md.")
        st.markdown("#### Response quality (human scoring)")
        st.caption("Rate agent messages from this session. Scores are only what a person records here; there are no automated or invented scores.")
        agent_msgs = db.q("SELECT id, account_id, ts, body FROM interactions WHERE origin='session' AND actor='agent' AND kind='message' ORDER BY rid DESC")
        if not agent_msgs:
            st.info("No agent messages in this session to rate yet.")
        else:
            st.selectbox("Message to rate", [m["id"] for m in agent_msgs], key="rate_msg",
                         format_func=lambda i: f"{i} · {next(m['body'] for m in agent_msgs if m['id'] == i)[:70].replace(chr(10), ' ')}…")
            cols = st.columns(3)
            for n, (k, d) in enumerate(E.CRITERIA.items()):
                cols[n % 3].slider(k.replace("_", " ").title(), 1, 5, 3, key=f"rate_{k}", help=d)
            st.text_input("Note (optional)", key="rate_note")
            st.button("Save rating", on_click=_rate, args=(db,))
        rt = db.q("SELECT * FROM ratings ORDER BY id")
        if rt:
            df = pd.DataFrame(rt)[["interaction_id", *E.CRITERIA, "note"]]
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.markdown("Response quality: **not evaluated**.")
        with st.expander("Criteria definitions"):
            for k, d in E.CRITERIA.items():
                st.markdown(f"- **{k.replace('_', ' ').title()}** — {d}")
        with st.expander("Optional: live-AI invariant runner"):
            st.markdown("Runs four scenarios against a real model and checks policy and state invariants (not prose quality). Requires your own key and spends model calls.")
            st.code("export ANTHROPIC_API_KEY=...\npython -m cso.evaluation --live", language="bash")
