from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import services as S, session, team
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import help as help_, nav, style, walkthroughs


def _open(aid: str, prod: str):
    session.select(aid, prod)
    session.goto("customer")


def _scan(db):
    rows = S.daily_scan(db)
    st.session_state["last_scan"] = rows
    sent = sum(r["Message sent"] == "Yes" for r in rows)
    session.record_action(f"Checked {len(rows)} journeys and sent {sent} message(s); {len(rows) - sent} were held back by the rules.",
                          why="Most customers should not be contacted: their rollout is later, they are progressing, or a frequency limit applies.", scope=("overview",))


def _continue(which: str):
    st.session_state["guided"] = which
    if which == "onboarding":
        session.select("ACC-001", "docs")
        session.goto("agent")
    else:
        session.select("ACC-041", "docs", meeting="MTG-001")
        session.goto("team")


def _has_progress(db, which: str) -> bool:
    if which == "onboarding":
        return db.one("SELECT COUNT(*) n FROM agent_runs WHERE account_id='ACC-001' AND origin='session'")["n"] > 0
    return db.one("SELECT COUNT(*) n FROM recommendations WHERE account_id='ACC-041' AND origin='session'")["n"] > 0


def _card(db, which: str, title: str, desc: str, button: str, start):
    info = walkthroughs.INFO[which]
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.markdown(desc)
        st.caption(f"About {info['minutes']} minutes")
        if _has_progress(db, which):
            c = st.columns(2)
            c[0].button("Continue where you left off", key=f"cont_{which}", on_click=_continue, args=(which,), type="primary", width="stretch")
            c[1].button("Start over", key=f"go_{which}", on_click=start, width="stretch", help=f"Resets only {info['customer']}. The other walkthrough keeps its progress.")
        else:
            st.button(button, key=f"go_{which}", type="primary", on_click=start, width="stretch")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Customer Success Orchestrator")
    st.markdown('<div class="cso-hero"><b>Help customers get started, resolve problems, and find the right learning support.</b></div>', unsafe_allow_html=True)
    st.markdown("Explore how an assistant uses customer context to provide guidance, prepare meeting notes, and involve a person when needed.")
    st.markdown("Choose a walkthrough below. No login or setup required.")
    st.caption("Interactive demo · Uses sample data and prepared responses.")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        _card(db, "onboarding", "Help a customer get started",
              "Maple Design is stuck setting up its software. See how the assistant offers guidance, involves support, and checks that setup is complete.",
              "Explore setup support", session.start_onboarding_demo)
    with c2:
        _card(db, "team", "Prepare for a customer conversation",
              "Northstar Retail needs help adopting a shared workflow. Review a meeting summary, suggested training, and useful talking points.",
              "Explore meeting preparation", session.start_team_demo)
    help_.render_guide(expanded=False)
    session.show_action("overview")
    with st.expander("About this demo"):
        st.markdown(
            "This is a **simulation of an agent workflow**. The assistant follows prepared scenarios and rules, and **no AI model is called**. "
            "Everything the assistant does inside the demo is real within your session: messages appear in the conversation, support tasks are created, reminders are paused or cancelled, "
            "and suggestions wait for a person to review them. All companies, people, usage and training records are sample data. Your changes are private to this browser session and reset when it ends.\n\n"
            "Both walkthroughs use the same customer records, product usage, support cases and rules, so they show one customer-context foundation used two ways. "
            "It demonstrates product and workflow design, not the behaviour of a language model.")

    with st.expander("See all example customers (optional)"):
        cnt = S.overview_counts(db)
        st.caption("Accounts count customers; journeys count one customer's setup of one product, so one account with three products can have three journeys.")
        cols = st.columns(5)
        cols[0].metric("Accounts monitored", cnt["monitored"], help="Accounts with at least one journey that is not completed or opted out.")
        cols[1].metric("Active journeys", cnt["active"], help="Journeys in: Monitoring, Guidance sent, Waiting for customer, Resolved (awaiting progress check). Excluded: Paused until rollout, Waiting for human, Completed, Opted out.")
        cols[2].metric("Accounts needing help", cnt["waiting_help"], help="Accounts with at least one open human task.")
        cols[3].metric("Open handoffs", cnt["open_handoffs"], help="Tasks waiting in the Human work queue.")
        cols[4].metric("Completed journeys", cnt["completed"], help="Journeys that reached Completed. Includes sample history.")
        st.markdown("**Accounts that need attention**")
        pri = S.priority_accounts(db)
        for r in pri:
            a, b, c3, d = st.columns([2, 1, 5, 1])
            a.markdown(f"**{r['Account']}**")
            b.markdown(style.product_pill(r["Product"]), unsafe_allow_html=True)
            c3.markdown(f"{style.badge(r['State'])} &nbsp; {r['Why']}", unsafe_allow_html=True)
            d.button("Open", key=f"open_{r['journey_id']}", on_click=_open, args=(r["account_id"], r["Product"]))
        st.markdown("**Daily scan**")
        st.caption("Checks every open journey with prepared rules and shows why most customers are *not* contacted.")
        live = session.mode() == "live"
        st.button("Run daily scan", on_click=_scan, args=(db,), disabled=live,
                  help="Disabled when an AI model is selected, so one click cannot trigger many paid calls." if live else None)
        if st.session_state.get("last_scan"):
            df = pd.DataFrame(st.session_state["last_scan"])
            st.dataframe(df.rename(columns={"Outcome": "Why"}), hide_index=True, width="stretch", height=300)
        snap = pd.DataFrame(db.q("SELECT product, state, COUNT(*) n FROM journeys GROUP BY product, state"))
        snap["state"] = snap["state"].map(STATE_LABEL)
        snap["product"] = snap["product"].map(PRODUCT_LABEL)
        st.markdown("**Journey states by product**")
        st.dataframe(snap.pivot_table(index="state", columns="product", values="n", fill_value=0, aggfunc="sum"), width="stretch")
    style.footer_label()
