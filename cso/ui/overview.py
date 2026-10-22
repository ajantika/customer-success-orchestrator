from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import services as S, session
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import nav, style


def _start_guided():
    session.reset_demo()
    st.session_state["guided"] = True
    st.session_state["sel_acc"], st.session_state["sel_prod"] = "ACC-001", "docs"
    session.flash("info", "Guided demo started with Maple Design. Follow the checklist at the top of this page.")


def _open(aid: str, prod: str):
    st.session_state["sel_acc"], st.session_state["sel_prod"] = aid, prod


def _scan(db):
    rows = S.daily_scan(db)
    st.session_state["last_scan"] = rows
    sent = sum(r["Message sent"] == "Yes" for r in rows)
    session.flash("success", f"Daily scan checked {len(rows)} journeys: {sent} message(s) sent, {len(rows) - sent} held back by rules.")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Customer Success Orchestrator")
    st.markdown("**Turns customer signals into timely guidance, agent actions and human handoffs, with business rules enforced in code.**")
    style.footer_label()
    c = S.overview_counts(db)
    cols = st.columns(5)
    cols[0].metric("Accounts monitored", c["monitored"], help="Accounts with at least one journey that is not completed or opted out.")
    cols[1].metric("Active onboarding journeys", c["active"], help="Journeys in monitoring, guidance sent, waiting for customer, or awaiting a progress check. Paused journeys are excluded.")
    cols[2].metric("Customers waiting for help", c["waiting_help"], help="Accounts with an open human task.")
    cols[3].metric("Open human handoffs", c["open_handoffs"])
    cols[4].metric("Completed journeys", c["completed"], help="Includes synthetic history.")

    if st.session_state.get("guided"):
        st.page_link(nav.PAGES["agent"], label="Guided demo is running. Continue on the Agent workspace", icon=":material/arrow_forward:")
    else:
        st.button("Start guided demo", type="primary", on_click=_start_guided,
                  help="Resets data, selects Maple Design and opens a step-by-step checklist on the Agent workspace.")
        if st.session_state.get("guided_hint") is None:
            pass
    st.markdown("### Accounts that need attention")
    pri = S.priority_accounts(db)
    if not pri:
        st.info("Nothing needs attention right now.")
    for r in pri:
        a, b, c3, d = st.columns([2, 1, 5, 1])
        a.markdown(f"**{r['Account']}**")
        b.markdown(style.product_pill(r["Product"]), unsafe_allow_html=True)
        c3.markdown(f"{style.badge(r['State'])} &nbsp; {r['Why']}", unsafe_allow_html=True)
        if d.button("Open", key=f"open_{r['journey_id']}", on_click=_open, args=(r["account_id"], r["Product"])):
            st.switch_page(nav.PAGES["customer"])

    st.markdown("### Run the daily scan")
    st.caption("Runs the scripted onboarding check on every open journey. Shows rules holding back outreach at scale: "
               "future rollouts, healthy progress, frequency limits, opt-outs and missing data.")
    live = session.mode() == "live"
    st.button("Run daily scan (scripted)", on_click=_scan, args=(db,), disabled=live,
              help="Disabled in Live AI mode so one click cannot spend many model calls." if live else None)
    if st.session_state.get("last_scan"):
        df = pd.DataFrame(st.session_state["last_scan"])
        st.dataframe(df, hide_index=True, width="stretch", height=300)

    st.markdown("### Journey states")
    snap = pd.DataFrame(db.q("SELECT product, state, COUNT(*) n FROM journeys GROUP BY product, state"))
    snap["state"] = snap["state"].map(STATE_LABEL)
    snap["product"] = snap["product"].map(PRODUCT_LABEL)
    st.dataframe(snap.pivot_table(index="state", columns="product", values="n", fill_value=0, aggfunc="sum"), width="stretch")
    with st.expander("About this prototype"):
        st.markdown("This is a fictional SaaS company with three products (Tasks, Docs, Support). All customers, usage and history are synthetic. "
                    "Public demo state lives in your browser session only and resets when the session ends. See the README for scope and limits.")
