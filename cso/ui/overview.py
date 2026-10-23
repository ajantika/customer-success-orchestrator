from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import services as S, session, team
from ..format import status, when
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import nav, style


def _open(aid: str, prod: str):
    session.select(aid, prod)
    session.goto("customer")


def _scan(db):
    rows = S.daily_scan(db)
    st.session_state["last_scan"] = rows
    sent = sum(r["Message sent"] == "Yes" for r in rows)
    session.flash("success", f"Daily scan checked {len(rows)} journeys: {sent} message(s) sent, {len(rows) - sent} held back by rules.")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Customer Success Orchestrator")
    st.markdown("**Help customers make progress, and help Account Teams recommend the right support and learning.**")
    style.footer_label()

    c1, c2 = st.columns(2, gap="large")
    with c1.container(border=True):
        st.markdown("#### Explore customer onboarding")
        st.caption("A customer is stuck setting up a product. Watch the assistant notice, help, read replies and hand off to a person.")
        st.button("Start with Maple Design", type="primary", on_click=session.start_onboarding_demo, key="go_onb",
                  help="Resets the demo data and opens Maple Design in the Agent workspace with a short guided checklist.")
    with c2.container(border=True):
        st.markdown("#### Prepare an Account Team meeting")
        st.caption("An Account Executive meets a customer tomorrow. See a brief, a learning recommendation with evidence, and the review step.")
        st.button("Start with Northstar Retail", type="primary", on_click=session.start_team_demo, key="go_team",
                  help="Resets the demo data and opens Northstar Retail's upcoming meeting with a short guided checklist.")
    st.caption("Both workflows share the same customer records, product usage, support cases, documentation and rules.")

    cnt = S.overview_counts(db)
    st.markdown("### Right now")
    st.caption("Accounts count customers; journeys count one customer's setup of one product, so an account with three products can have three journeys.")
    cols = st.columns(5)
    cols[0].metric("Accounts monitored", cnt["monitored"], help="Accounts with at least one journey that is not completed or opted out.")
    cols[1].metric("Active journeys", cnt["active"], help="Journeys in: Monitoring, Guidance sent, Waiting for customer, Resolved (awaiting progress check). Excluded: Paused until rollout, Waiting for human, Completed, Opted out.")
    cols[2].metric("Accounts needing help", cnt["waiting_help"], help="Accounts with at least one open human task.")
    cols[3].metric("Open handoffs", cnt["open_handoffs"], help="Tasks waiting in the Human work queue.")
    cols[4].metric("Completed journeys", cnt["completed"], help="Journeys that reached Completed. Includes synthetic history.")
    up = len(team.upcoming(db, 7))
    st.caption(f"{up} customer meeting(s) in the next 7 days on the Account Team Assistant page.")

    st.markdown("### Accounts that need attention")
    pri = S.priority_accounts(db)
    if not pri:
        st.info("Nothing needs attention right now.")
    for r in pri:
        a, b, c3, d = st.columns([2, 1, 5, 1])
        a.markdown(f"**{r['Account']}**")
        b.markdown(style.product_pill(r["Product"]), unsafe_allow_html=True)
        c3.markdown(f"{style.badge(r['State'])} &nbsp; {r['Why']}", unsafe_allow_html=True)
        d.button("Open", key=f"open_{r['journey_id']}", on_click=_open, args=(r["account_id"], r["Product"]))

    st.markdown("### Run the daily scan")
    st.caption("Runs the onboarding check on every open journey, using prepared rules. It shows the rules holding back outreach at scale: "
               "future rollouts, healthy progress, frequency limits, opt-outs and missing data.")
    live = session.mode() == "live"
    st.button("Run daily scan", on_click=_scan, args=(db,), disabled=live,
              help="Disabled when an AI model is selected, so one click cannot trigger many paid calls." if live else None)
    if st.session_state.get("last_scan"):
        df = pd.DataFrame(st.session_state["last_scan"])
        st.dataframe(df.rename(columns={"Outcome": "Why"}), hide_index=True, width="stretch", height=300)

    with st.expander("Journey states by product"):
        snap = pd.DataFrame(db.q("SELECT product, state, COUNT(*) n FROM journeys GROUP BY product, state"))
        snap["state"] = snap["state"].map(STATE_LABEL)
        snap["product"] = snap["product"].map(PRODUCT_LABEL)
        st.dataframe(snap.pivot_table(index="state", columns="product", values="n", fill_value=0, aggfunc="sum"), width="stretch")
    with st.expander("About this prototype"):
        st.markdown("This is a fictional SaaS company with three products (Tasks, Docs, Support). All customers, usage and history are synthetic. "
                    "Your changes live only in this browser session and reset when it ends. See the README for scope and limits.")
