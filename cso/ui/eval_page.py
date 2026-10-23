from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .. import evaluation as E, services as S, session, team
from ..format import when
from ..models import PRODUCT_LABEL, STATE_LABEL
from .. import flags
from . import style

TABS = ["Observed in this session", "Sample history", "System evaluation"]


def _run_checks(db):
    res = E.run_workflow_checks()
    E.record_results(db, res)
    st.session_state["tab_eval"] = TABS[2]
    st.session_state["eval_msg"] = ("success" if all(r["passed"] for r in res) else "warning", f"Ran {len(res)} workflow checks: {sum(r['passed'] for r in res)} passed.")


def _rate(db):
    ss = st.session_state
    kind = "message" if ss.get("rate_kind") == "Agent message" else "recommendation"
    crit = E.CRITERIA if kind == "message" else {**E.CRITERIA, **E.REC_CRITERIA}
    subject = ss.get("rate_msg") if kind == "message" else ss.get("rate_rec")
    try:
        E.save_rating(db, subject, {k: ss[f"rate_{kind}_{k}"] for k in crit}, ss.get("rate_note", ""), kind)
        ss["tab_eval"] = TABS[2]
        ss["eval_msg"] = ("success", f"Rating saved for {subject}.")
    except ValueError as e:
        ss["eval_msg"] = ("warning", str(e))


def _tab_session(db):
    m = S.session_metrics(db)
    tm = team.team_metrics(db, "session")
    st.info("Counts only what happened in **your current session**. They reset with the demo and are not outcomes.")
    st.markdown("#### Customer onboarding agent")
    rows = [
        ("Agent runs", m["runs"], "Agent loop executions started in this session.", "Count"),
        ("Messages sent by the agent", m["agent_messages"], "Messages written to the simulated inbox.", "Count"),
        ("Customer replies", m["customer_messages"], "Inbound simulated messages.", "Count"),
        ("Unnecessary outreach prevented", m["outreach_prevented"], "Proactive runs that ended without a message because a rule said no, plus blocked sends and repeats of guidance the customer tried.", "Count"),
        ("Policy-override messages rejected", m["policy_overrides"], "Customer messages matching override patterns.", "Count"),
        ("Handoffs created / resolved", f"{m['handoffs_created']} / {m['handoffs_resolved']}", "Tasks created and closed in this session.", "Count"),
        ("Journeys completed this session", f"{m['journeys_completed']} of {m['open_at_start']}", "Journeys that reached Completed after the session began.", f"{m['open_at_start']} journeys open at start"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Measure", "Value", "Definition", "Denominator"]), hide_index=True, width="stretch")
    st.markdown("#### Tool calls, split by what actually happened")
    tot = m["tool_calls"]
    tr = [
        ("Successful executions", m["tool_success"], "Tool ran and changed or returned what was asked."),
        ("Expected policy blocks", m["tool_policy_blocks"], "A rule correctly refused the call (for example frequency limit, opt-out, wrong account, missing evidence). Not an error."),
        ("Technical failures", m["tool_technical_failures"], "The tool could not do its job (service unavailable, invalid input, unexpected error)."),
        ("Duplicate actions prevented", m["duplicates_prevented"], "A repeated idempotency key or an already-open task or recommendation returned the existing result."),
    ]
    st.dataframe(pd.DataFrame(tr, columns=["Measure", "Count", "Definition"]).assign(**{"Share of tool calls": lambda d: [S.pct(int(c), tot) if i < 3 else "n/a" for i, c in enumerate(d["Count"])]}),
                 hide_index=True, width="stretch")
    if m["error_codes"]:
        st.dataframe(pd.DataFrame(m["error_codes"]).rename(columns={"error": "Code", "n": "Count", "kind": "Type"}), hide_index=True)
    st.markdown("#### Meeting preparation")
    ar = [
        ("Eligible meetings", tm["eligible"], f"Scheduled meetings in the next 14 days ({tm['scope']}).", "Count"),
        ("Briefs generated", tm["briefs_generated"], "Distinct meetings with a saved brief.", f"{tm['eligible']} eligible meetings"),
        ("Briefs viewed", tm["briefs_viewed"], "Distinct meetings a reviewer opened a brief for. One per reviewer; rerenders do not count.", f"{tm['briefs_generated']} briefs generated"),
        ("Recommendations reviewed", tm["reviewed"], "Distinct recommendations a person acted on.", f"{tm['recs']} recommendations"),
        ("Accepted / edited", f"{tm['accepted']} / {tm['edited']}", "Distinct recommendations accepted or edited (an edited one may also be accepted).", f"{tm['reviewed']} reviewed"),
        ("Dismissed / deferred", f"{tm['dismissed']} / {tm['deferred']}", "Distinct recommendations dismissed or deferred, each with a reason.", f"{tm['reviewed']} reviewed"),
        ("Marked discussed", tm["discussed"], "Recommendations the account team says were raised with the customer.", f"{tm['accepted'] + tm['edited']} accepted or edited"),
        ("Learners enrolled / started / completed", f"{tm['enrolled']} / {tm['started']} / {tm['completed']}", "Sample customer learning updates, tracked separately from the reviewer's decision.", "Learners"),
    ]
    st.dataframe(pd.DataFrame(ar, columns=["Measure", "Value", "Definition", "Denominator"]), hide_index=True, width="stretch")
    if not m["runs"] and not tm["briefs_generated"]:
        st.caption("No activity yet. Start a guided demo from the Overview page.")


def _tab_seed(db):
    sd = S.seeded_metrics(db)
    tm = team.team_metrics(db, "seed")
    st.warning("**Sample data.** Generated from a fixed random seed. Not real customers and not evidence of any improvement.")
    comp = pd.DataFrame([{"Product": PRODUCT_LABEL[r["product"]], "Rollout started": r["rollout_started"], "Completed": r["completed"],
                          "Setup completion": S.pct(r["completed"], r["rollout_started"])} for r in sd["completion"]])
    st.markdown("**Setup completion** · journeys completed ÷ journeys whose planned rollout had started when the data was generated")
    st.dataframe(comp, hide_index=True, width="stretch")
    st.markdown("**Time to first milestone** · median days from planned rollout start to the first milestone event, accounts with at least one milestone")
    st.dataframe(pd.DataFrame([{"Product": PRODUCT_LABEL[r["product"]], "Accounts (denominator)": r["accounts"], "Median days": r["median_days"] if r["median_days"] is not None else "n/a"} for r in sd["time_to_first"]]),
                 hide_index=True, width="stretch")
    st.markdown("**Sample support tasks**")
    st.dataframe(pd.DataFrame(sd["handoffs"]).rename(columns={"team": "Team", "status": "Status", "n": "Tasks"}), hide_index=True)
    st.markdown("**Meeting preparation history (sample)** · past meetings with a prepared brief")
    st.dataframe(pd.DataFrame([
        ("Past meetings", tm["eligible"], "Completed meetings in the seeded history"), ("Briefs generated / viewed", f"{tm['briefs_generated']} / {tm['briefs_viewed']}", f"of {tm['eligible']} meetings"),
        ("Accepted / edited / dismissed / deferred", f"{tm['accepted']} / {tm['edited']} / {tm['dismissed']} / {tm['deferred']}", f"of {tm['recs']} recommendations"),
        ("Marked discussed", tm["discussed"], f"of {tm['accepted'] + tm['edited']} accepted or edited"), ("Learners enrolled / started / completed", f"{tm['enrolled']} / {tm['started']} / {tm['completed']}", "synthetic")],
        columns=["Measure", "Value", "Denominator"]), hide_index=True, width="stretch")
    flat = [{"Product": PRODUCT_LABEL[p], "State": STATE_LABEL[s], "Journeys": n} for p, d in sd["states"].items() for s, n in d.items()]
    fig = px.bar(pd.DataFrame(flat), x="Journeys", y="State", color="Product", orientation="h", title="Journey states in the sample data",
                 color_discrete_sequence=["#8b8cf8", "#5eead4", "#fbbf77"], template="plotly_dark")
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=40, b=0), yaxis=dict(categoryorder="total ascending"), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")
    with st.expander("How a real pilot could measure usefulness"):
        st.markdown(
            "Sample numbers cannot show that either workflow changes outcomes. A pilot could:\n"
            "- **Onboarding:** randomly assign comparable eligible accounts to agent-assisted and business-as-usual groups (or hold some out), pre-register the main metric "
            "(for example, share reaching the first milestone within a set number of days) and review opt-outs, complaints and escalations as guardrails.\n"
            "- **Meeting preparation usefulness:** ask reviewers to rate each recommendation, and track how often briefs are opened, accepted, edited and discussed.\n"
            "- **Preparation time:** time a sample of meeting preparations with and without the brief, using the same meeting types.\n"
            "- **Field adoption:** compare which teams and roles use the page week over week.\n"
            "- **Downstream learning:** follow enrolment and completion for customers whose team discussed a recommendation versus comparable meetings where it was not raised. "
            "Without randomisation or a comparable group, differences could reflect account size, intent or seasonality, so they would not be claimed as impact.")


def _tab_system(db):
    st.markdown("#### Workflow checks (deterministic)")
    st.caption("These test application behaviour (rules, tools, state, idempotency, review workflow) on a fresh seeded database per check. They are **not** a language-quality evaluation. "
               "Navigation and selection checks run in the pytest UI suite (see EVALUATION.md).")
    st.button("Run workflow checks", type="primary", on_click=_run_checks, args=(db,))
    msg = st.session_state.pop("eval_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    res = db.q("SELECT * FROM eval_results WHERE suite='workflow' ORDER BY id")
    if res:
        st.markdown(f"**Last run:** {sum(r['passed'] for r in res)} of {len(res)} passed · {when(res[0]['ran_at'])}")
        st.dataframe(pd.DataFrame([{"Check": r["name"], "Result": "Pass" if r["passed"] else "Fail", "Evidence": r["detail"][:260]} for r in res]), hide_index=True, width="stretch")
    else:
        st.markdown("**Not evaluated** in this session yet. The same checks run with `pytest`.")
    st.markdown("#### Response quality (human scoring)")
    st.caption("Scores are only what a person records here. There are no automated or invented scores.")
    st.radio("What are you rating?", ["Agent message", "Meeting suggestion"], horizontal=True, key="rate_kind")
    kind = "message" if st.session_state.get("rate_kind", "Agent message") == "Agent message" else "recommendation"
    if kind == "message":
        items = db.q("SELECT id, body FROM interactions WHERE origin='session' AND actor='agent' AND kind='message' ORDER BY rid DESC")
        crit = E.CRITERIA
        if items:
            st.selectbox("Message to rate", [m["id"] for m in items], key="rate_msg",
                         format_func=lambda i: next(m["body"] for m in items if m["id"] == i)[:70].replace("\n", " ") + "…")
    else:
        items = db.q("SELECT id, title FROM recommendations WHERE origin='session' ORDER BY created_at DESC, id DESC")
        crit = {**E.CRITERIA, **E.REC_CRITERIA}
        if items:
            st.selectbox("Recommendation to rate", [m["id"] for m in items], key="rate_rec", format_func=lambda i: f"{i} · " + next(m["title"] for m in items if m["id"] == i)[:70])
    if not items:
        st.info("Nothing from this session to rate yet.")
    else:
        cols = st.columns(3)
        for n, (k, d) in enumerate(crit.items()):
            cols[n % 3].slider(k.replace("_", " ").title(), 1, 5, 3, key=f"rate_{kind}_{k}", help=d)
        st.text_input("Note (optional)", key="rate_note")
        st.button("Save rating", on_click=_rate, args=(db,))
    rt = db.q("SELECT * FROM ratings ORDER BY id")
    if rt:
        cols_ = ["interaction_id", "kind", *E.CRITERIA, *E.REC_CRITERIA, "note"]
        st.dataframe(pd.DataFrame(rt)[cols_].rename(columns={"interaction_id": "item"}), hide_index=True, width="stretch")
    else:
        st.markdown("Response quality: **not evaluated**.")
    with st.expander("Criteria definitions"):
        for k, d in {**E.CRITERIA, **E.REC_CRITERIA}.items():
            st.markdown(f"- **{k.replace('_', ' ').title()}** — {d}")
    if flags.advanced():
        with st.expander("Optional: live AI check"):
            st.markdown("Runs scenarios against a real model and checks policy and state rules (not prose quality). Requires your own key and spends model calls.")
            st.code("export ANTHROPIC_API_KEY=...\npython -m cso.evaluation --live", language="bash")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Evaluation and outcomes")
    st.caption("Three separate views. Nothing here is a measured business result: all customers and history are sample data.")
    if st.session_state.get("tab_eval") not in TABS:
        st.session_state["tab_eval"] = TABS[0]
    view = st.radio("View", TABS, horizontal=True, key="tab_eval", label_visibility="collapsed")
    {TABS[0]: _tab_session, TABS[1]: _tab_seed, TABS[2]: _tab_system}[view](db)
