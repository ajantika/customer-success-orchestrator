from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import rules, services as S, session, team
from ..format import status, when
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import help as help_, style

EXAMPLES = [("ACC-001", "Maple Design", "demonstrates a setup blocker."), ("ACC-041", "Northstar Retail", "demonstrates a potential learning need.")]


def _on_select():
    new = st.session_state.get("w_ov_acct")
    session.select(new, session.default_product(session.get_db(), new))


def _pick(aid: str):
    session.select(aid, session.default_product(session.get_db(), aid))


def _open_setup():
    session.goto("agent")


def _open_brief():
    db = session.get_db()
    m = db.one("SELECT id FROM meetings WHERE account_id=? AND status='scheduled' AND starts_at>? ORDER BY starts_at LIMIT 1", (st.session_state["acct"], team.to_iso(db.now())))
    session.select(st.session_state["acct"], meeting=m["id"] if m else None)
    session.goto("team")


def _scan(db):
    rows = S.daily_scan(db)
    st.session_state["last_scan"] = rows
    sent = sum(r["Message sent"] == "Yes" for r in rows)
    session.record_action(f"Checked {len(rows)} journeys and sent {sent} message(s); {len(rows) - sent} were held back by the rules.",
                          why="Most customers should not be contacted: their rollout is later, they are progressing, or a frequency limit applies.", scope=("overview",))


def _open_customer(aid: str, prod: str):
    session.select(aid, prod)
    session.goto("customer")


def _preview(db, aid: str):
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    js = db.q("SELECT * FROM journeys WHERE account_id=? ORDER BY product", (aid,))
    meeting = db.one("SELECT * FROM meetings WHERE account_id=? AND status='scheduled' AND starts_at>? ORDER BY starts_at LIMIT 1", (aid, team.to_iso(db.now())))
    with st.container(border=True):
        st.markdown(f"#### {acc['name']} &nbsp; <span class='cso-pill'>{(acc['lifecycle'] or '').capitalize()} stage</span>", unsafe_allow_html=True)
        st.markdown(f"**Customer goal.** {acc['goal'] or 'Not recorded'}")
        if js:
            lines = []
            for j in js:
                pr = rules.progress(db, aid, j["product"])
                lines.append(f"- **{PRODUCT_LABEL[j['product']]}**: {pr['done_count']} of {pr['total']} setup steps done · {STATE_LABEL[j['state']].lower()}")
            st.markdown("**Products and setup status**\n" + "\n".join(lines))
            dflt = next((j for j in js if j["product"] == session.default_product(db, aid)), js[0])
            st.markdown("**What you can explore.** " + rules.plain_decision(db, dflt["id"])["headline"] +
                        (f" A conversation is scheduled for {when(meeting['starts_at'])}, so you can prepare a brief for it." if meeting else ""))
        else:
            st.markdown("**Products and setup status.** None yet. This customer is still evaluating the product.")
            st.markdown("**What you can explore.** " + (f"A conversation is scheduled for {when(meeting['starts_at'])}: {meeting['purpose']}." if meeting else "There is nothing to explore yet."))
    c1, c2 = st.columns(2, gap="large")
    with c1.container(border=True, height=250):
        st.markdown("#### Setup support")
        st.markdown("Review setup progress, provide relevant instructions, and involve Support when needed.")
        if js:
            st.button("Open setup support", key="open_setup", type="primary", on_click=_open_setup, width="stretch")
        else:
            st.button("Open setup support", key="open_setup", disabled=True, width="stretch")
            st.caption(f"{acc['name']} has not bought anything yet, so there is no setup to support.")
    with c2.container(border=True, height=250):
        st.markdown("#### Customer brief and learning recommendations")
        st.markdown("Review usage and learning progress to prepare relevant next steps and talking points.")
        if meeting:
            st.button("Prepare customer brief", key="open_brief", type="primary", on_click=_open_brief, width="stretch")
        else:
            st.button("Prepare customer brief", key="open_brief", disabled=True, width="stretch")
            st.caption(f"No conversation with {acc['name']} is scheduled in the sample calendar, so there is no brief to prepare.")
    with st.popover("Reset this customer's demo activity"):
        st.markdown(f"This undoes what you did with **{acc['name']}** in this session: messages, support tasks, recommendations and setup progress. "
                    "Other customers are not changed. The demo clock returns to the original date.")
        st.button(f"Yes, reset {acc['name']}", key="reset_cust", on_click=session.reset_customer, args=(aid,), type="primary")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Customer Success Orchestrator")
    st.markdown('<div class="cso-hero"><b>Understand where a customer needs help and decide what to do next.</b></div>', unsafe_allow_html=True)
    st.markdown("Review customer goals, setup progress, usage, support issues, and learning needs. Choose a customer to begin.")
    st.caption("Interactive demo · Sample data · Prepared responses and rules. No live AI model is called.")

    accts = db.q("SELECT id, name FROM accounts ORDER BY name")
    ids = [a["id"] for a in accts]
    names = {a["id"]: a["name"] for a in accts}
    cur = st.session_state.get("acct") if st.session_state.get("acct") in ids else None
    st.session_state["w_ov_acct"] = cur
    st.selectbox("Select a customer", ids, index=None, format_func=lambda i: names[i], placeholder="Select a customer…", key="w_ov_acct", on_change=_on_select)
    with st.container():
        st.markdown("**Not sure where to start?**")
        c = st.columns(2)
        for col, (aid, name, blurb) in zip(c, EXAMPLES):
            col.markdown(f"**{name}** {blurb}")
            col.button(f"Select {name}", key=f"ex_{aid}", on_click=_pick, args=(aid,), disabled=(cur == aid), width="stretch")
    session.show_action("overview")
    if cur:
        _preview(db, cur)
    else:
        st.info("No customer is selected yet. Choose one above, or pick an example, to see what you can explore.")
    help_.render_guide(expanded=False)
    with st.expander("About this demo"):
        st.markdown(
            "This is a **simulation of an agent workflow**. The assistant follows prepared scenarios and rules, and **no AI model is called**. "
            "Everything the assistant does inside the demo is real within your session: messages appear in the conversation, support tasks are created, reminders are paused or cancelled, "
            "and suggestions wait for a person to review them. All companies, people, usage and training records are sample data. Your changes are private to this browser session and reset when it ends.\n\n"
            "Setup support and the customer brief use the same customer records, product usage, support cases and rules, so they show one customer-context foundation used two ways. "
            "It demonstrates product and workflow design, not the behaviour of a language model.")
    with st.expander("See all example customers (optional)"):
        cnt = S.overview_counts(db)
        st.caption("Accounts count customers; journeys count one customer's setup of one product, so one account with three products can have three journeys.")
        cols = st.columns(5)
        cols[0].metric("Accounts monitored", cnt["monitored"], help="Accounts with at least one journey that is not completed or opted out.")
        cols[1].metric("Active journeys", cnt["active"], help="Journeys in: Monitoring, Guidance sent, Waiting for customer, Resolved (awaiting progress check). Excluded: Paused until rollout, Waiting for human, Completed, Opted out.")
        cols[2].metric("Accounts needing help", cnt["waiting_help"], help="Accounts with at least one open support task.")
        cols[3].metric("Open support tasks", cnt["open_handoffs"], help="Tasks waiting on a person.")
        cols[4].metric("Completed journeys", cnt["completed"], help="Journeys that reached Completed. Includes sample history.")
        st.markdown("**Customers that need attention**")
        for r in S.priority_accounts(db):
            a, b, c3, d = st.columns([2, 1, 5, 1])
            a.markdown(f"**{r['Account']}**")
            b.markdown(style.product_pill(r["Product"]), unsafe_allow_html=True)
            c3.markdown(f"{style.badge(r['State'])} &nbsp; {r['Why']}", unsafe_allow_html=True)
            d.button("Open", key=f"open_{r['journey_id']}", on_click=_open_customer, args=(r["account_id"], r["Product"]))
        st.markdown("**Daily scan**")
        st.caption("Checks every open journey with prepared rules and shows why most customers are *not* contacted.")
        st.button("Run daily scan", on_click=_scan, args=(db,))
        if st.session_state.get("last_scan"):
            st.dataframe(pd.DataFrame(st.session_state["last_scan"]).rename(columns={"Outcome": "Why"}), hide_index=True, width="stretch", height=300)
    style.footer_label()
