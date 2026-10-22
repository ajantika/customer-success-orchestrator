from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rules, session
from ..db import from_iso
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import style


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Customer workspace")
    aid, jid = style.account_picker(db, with_product=False)
    if not aid:
        st.info("Select a customer above to see their goal, setup progress, open issues and full timeline.")
        return
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    contact = rules.admin_contact(db, aid)
    now = db.now()
    st.markdown(f"#### {acc['name']} &nbsp; <span class='cso-pill'>{acc['segment']}</span> <span class='cso-pill'>synthetic</span>", unsafe_allow_html=True)
    st.markdown(f"**Customer goal:** {acc['goal'] or '_missing_'}")
    st.caption(f"Product data last synced: {acc['data_refreshed_at'][:16].replace('T', ' ')} · Demo clock: {now:%Y-%m-%d %H:%M}")

    subs = db.q("SELECT product FROM subscriptions WHERE account_id=? ORDER BY product", (aid,))
    plans = {r["product"]: r["planned_start"] for r in db.q("SELECT * FROM rollout_plans WHERE account_id=?", (aid,))}
    st.markdown("**Purchased products and rollout plan**")
    rows = []
    for s in subs:
        p = s["product"]
        start = plans.get(p)
        rows.append({"Product": PRODUCT_LABEL[p], "Planned rollout": start[:10] if start else "Not on file",
                     "Rollout status": "No plan" if not start else ("Started" if from_iso(start) <= now else f"Planned in {(from_iso(start) - now).days} days")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.markdown("### Onboarding milestones and journey status")
    for s in subs:
        p = s["product"]
        pr = rules.progress(db, aid, p)
        j = db.one("SELECT * FROM journeys WHERE account_id=? AND product=?", (aid, p))
        usage = db.one("SELECT COUNT(*) n FROM product_events WHERE account_id=? AND product=? AND event_type='usage_session' AND ts>=?",
                       (aid, p, (now.replace(hour=0) - pd.Timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")))["n"]
        with st.container(border=True):
            h1, h2 = st.columns([3, 2])
            h1.markdown(f"**{PRODUCT_LABEL[p]}** &nbsp; {style.badge(j['state'])}", unsafe_allow_html=True)
            h2.caption(f"{pr['done_count']} of {pr['total']} milestones · {usage} usage sessions in the last 14 days (synthetic)")
            st.progress(pr["done_count"] / pr["total"] if pr["total"] else 0)
            st.markdown("  \n".join(f"{'✅' if m['done'] else '⬜'} {m['label']}" + (f" _({m['done_at'][:10]})_" if m["done"] else "") for m in pr["milestones"]))
            el = rules.evaluate_outreach(db, j["id"])
            verdict = "Eligible for outreach" if el.allowed else "Not eligible for outreach"
            with st.expander(f"{verdict} — why?", expanded=(p == st.session_state.get("sel_prod"))):
                st.markdown("\n".join(f"- {'✅' if c.passed else '❌'} **{c.code.replace('_', ' ')}**: {c.message}" for c in el.checks))
                st.caption("Rules are evaluated in code before any message is sent. Thresholds are demo policy and configurable.")

    st.markdown("### Open support issues")
    cases = db.q("SELECT id, product, subject, category, created_at FROM support_cases WHERE account_id=? AND status='open'", (aid,))
    tasks = db.q("SELECT id, product, issue, priority, team, status, assignee FROM human_tasks WHERE account_id=? AND status!='resolved'", (aid,))
    if cases or tasks:
        if cases:
            st.dataframe(pd.DataFrame(cases), hide_index=True, width="stretch")
        if tasks:
            st.dataframe(pd.DataFrame(tasks), hide_index=True, width="stretch")
    else:
        st.info("No open support cases or human tasks for this customer.")

    st.markdown("### Contact preferences")
    ct = db.q("SELECT name, role, email, preferred_channel, opted_out, consent FROM contacts WHERE account_id=?", (aid,))
    for c in ct:
        c["email"] = c["email"] or "MISSING"
        c["opted_out"] = "Yes" if c["opted_out"] else "No"
        c["consent"] = "Yes" if c["consent"] else "No"
    st.dataframe(pd.DataFrame(ct), hide_index=True, width="stretch")

    st.markdown("### Unified timeline")
    f = st.multiselect("Show", ["customer", "agent", "human", "system"], default=["customer", "agent", "human", "system"], key="tl_filter")
    items = db.q("SELECT * FROM interactions WHERE account_id=? ORDER BY rid DESC LIMIT 150", (aid,))
    items = [i for i in items if i["actor"] in f]
    if not items:
        st.info("No activity yet. Run the onboarding check on the Agent workspace.")
    with st.container(height=480):
        for i in items:
            style.bubble(i)
        if any(i["origin"] == "seed" for i in items):
            st.caption("Entries from before this session are seeded synthetic history.")
