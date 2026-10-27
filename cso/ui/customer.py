from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd
import streamlit as st

from .. import rules, session
from ..db import from_iso, to_iso
from ..format import status, when
from ..models import PRODUCT_LABEL, STATE_LABEL
from . import style

ACTOR = {"customer": "Customer", "agent": "Assistant", "human": "Support team", "system": "System"}
KIND = {"proactive": "setup guidance", "reply": "reply", "status_update": "update", "confirmation": "confirmation"}


def _open_setup(aid):
    session.select(aid)
    session.goto("agent")


def _open_brief(mid, aid):
    session.select(aid, meeting=mid)
    session.goto("team")


def _timeline_text(i: dict) -> str:
    body = i["body"]
    if i["kind"] == "message":
        text = body.split("\n\n", 1)[-1] if body.startswith("Subject:") else body
        text = " ".join(text.split())
        short = text if len(text) <= 150 else text[:147] + "…"
        if i["actor"] == "customer":
            return f"Customer replied by {i['channel']}: “{short}”"
        kind = KIND.get(json.loads(i["signals"]).get("message_kind"), "message")
        return f"Assistant sent a {kind} by {i['channel']}: “{short}”"
    return body


def _decision_box(db, jid: str):
    d = rules.plain_decision(db, jid)
    with st.container(border=True):
        st.markdown(f"**Suggested next step and why**")
        st.markdown(f"{d['headline']}")
        st.markdown(f"**Next:** {d['next_step']}")
        with st.expander("Why this decision?"):
            st.caption("These rules are checked in code before any message is sent. The thresholds are demo values. “Holding” means a condition is not met right now, which is often expected.")
            st.dataframe(pd.DataFrame([{"Rule": r["rule"], "Status": "Clear" if r["met"] else "Holding", "Detail": r["note"]} for r in d["details"]]), hide_index=True, width="stretch")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Customer workspace")
    st.caption("See this customer's goals, products, setup progress, and recent activity.")
    aid, jid = style.account_picker(db)
    if not aid:
        st.info("Choose a customer above, or pick one on the Overview, to see their goal, setup progress, open issues and timeline.")
        return
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    prod = st.session_state.get("prod")
    now = db.now()
    style.context_line(db, aid, prod)
    st.markdown(f"<span class='cso-pill'>{(acc['lifecycle'] or '').capitalize()} stage</span> <span class='cso-pill'>{acc['segment']}</span> "
                f"<span class='cso-pill'>Owner: {acc['owner'] or 'unassigned'}</span> <span class='cso-pill'>Technical lead: {acc['solutions_architect'] or 'unassigned'}</span>", unsafe_allow_html=True)
    st.markdown(f"**Customer goal.** {acc['goal'] or 'Not recorded'}")
    st.caption(f"Product data last synced {when(acc['data_refreshed_at'])} · Demo clock {when(now)}")

    subs = db.q("SELECT product FROM subscriptions WHERE account_id=? ORDER BY product", (aid,))
    plans = {r["product"]: r["planned_start"] for r in db.q("SELECT * FROM rollout_plans WHERE account_id=?", (aid,))}
    if jid:
        _decision_box(db, jid)
    st.markdown("### Products and setup progress")
    if not subs:
        st.info(f"{acc['name']} is still evaluating the product and has not bought anything yet, so there is no rollout plan, setup progress or usage to show. "
                "No sample usage has been invented for this example.")
    period_end = now.date()
    period_start = (now - timedelta(days=14)).date()
    for s in subs:
        p = s["product"]
        pr = rules.progress(db, aid, p)
        j = db.one("SELECT * FROM journeys WHERE account_id=? AND product=?", (aid, p))
        start = plans.get(p)
        rollout = "No rollout date on file" if not start else (f"Rollout started {when(start, False)}" if from_iso(start) <= now else f"Rollout planned for {when(start, False)} (in {(from_iso(start) - now).days} days)")
        with st.container(border=True):
            h1, h2 = st.columns([3, 2])
            h1.markdown(f"**{PRODUCT_LABEL[p]}**{' (selected)' if p == prod else ''} &nbsp; {style.badge(j['state'])}", unsafe_allow_html=True)
            h2.caption(rollout)
            st.progress(pr["done_count"] / pr["total"] if pr["total"] else 0, text=f"Setup: {pr['done_count']} of {pr['total']} steps done")
            if pr["complete"]:
                st.markdown("Setup is complete. Check whether the team is regularly using the intended workflow.")
            st.caption(f"Recent usage: {pr['usage_recent']} sessions in the last 14 days ({period_start:%b} {period_start.day} – {period_end:%b} {period_end.day}), "
                       f"compared with {pr['usage_prior']} in the 30 days before.")
            if pr["workflow_recent"] or pr["workflow_prior"]:
                st.caption(f"Activity in the shared documentation workflow: {pr['workflow_recent']} in the last 14 days, {pr['workflow_prior']} in the 30 days before. "
                           "This is separate from general product usage.")
            with st.expander("Setup steps", expanded=(p == prod and not pr["complete"])):
                st.markdown("  \n".join(f"{'✅' if m['done'] else '⬜'} {m['customer_label']}" + (f" _({when(m['done_at'], False)})_" if m["done"] else "") for m in pr["milestones"]))

    st.markdown("### Open support issues")
    cases = db.q("SELECT id, product, subject, category, created_at FROM support_cases WHERE account_id=? AND status='open'", (aid,))
    tasks = db.q("SELECT id, product, issue, priority, team, status, assignee FROM human_tasks WHERE account_id=? AND status!='resolved'", (aid,))
    if cases or tasks:
        if cases:
            st.dataframe(pd.DataFrame([{"Case": c["id"], "Product": PRODUCT_LABEL[c["product"]], "Subject": c["subject"], "Type": c["category"].capitalize(), "Opened": when(c["created_at"], False)} for c in cases]),
                         hide_index=True, width="stretch")
        if tasks:
            st.dataframe(pd.DataFrame([{"Task": t["id"], "Product": PRODUCT_LABEL[t["product"]], "Issue": t["issue"], "Priority": t["priority"].capitalize(), "Owner": t["team"],
                                        "Status": status(t["status"]), "Assignee": t["assignee"] or "Not assigned"} for t in tasks]), hide_index=True, width="stretch")
    else:
        st.caption(f"No open support issues for {acc['name']}.")

    learn = db.q("SELECT l.course_id, c.title, l.status, COUNT(*) n FROM learner_records l JOIN courses c ON c.id=l.course_id WHERE l.account_id=? GROUP BY l.course_id, l.status ORDER BY l.course_id", (aid,))
    if learn:
        st.markdown("### Learning progress")
        st.caption("Sample learner records. They show who has taken which course; they do not prove a skills gap or a need.")
        pivot = pd.DataFrame(learn).pivot_table(index="title", columns="status", values="n", fill_value=0, aggfunc="sum")
        pivot.columns = [status(c) for c in pivot.columns]
        st.dataframe(pivot, width="stretch")
    meets = db.q("SELECT * FROM meetings WHERE account_id=? AND status='scheduled' ORDER BY starts_at", (aid,))
    if meets:
        st.markdown("### Upcoming conversations")
        for m in meets:
            c1, c2 = st.columns([5, 2])
            c1.markdown(f"**{when(m['starts_at'])}** · {m['purpose']} · {m['owner']}")
            c2.button("Prepare customer brief", key=f"mb_{m['id']}", on_click=_open_brief, args=(m["id"], aid), width="stretch")
    with st.expander("Contact preferences"):
        ct = db.q("SELECT name, role, email, preferred_channel, opted_out, consent FROM contacts WHERE account_id=?", (aid,))
        for c in ct:
            c["email"] = c["email"] or "MISSING"
            c["opted_out"] = "Yes" if c["opted_out"] else "No"
            c["consent"] = "Yes" if c["consent"] else "No"
        st.dataframe(pd.DataFrame(ct).rename(columns={"preferred_channel": "preferred channel", "opted_out": "opted out"}), hide_index=True, width="stretch")

    st.markdown("### Unified timeline")
    st.caption("See this customer's messages, support updates, and setup progress in one place.")
    items = db.q("SELECT * FROM interactions WHERE account_id=? ORDER BY rid DESC LIMIT 200", (aid,))
    if not items:
        if subs:
            st.info(f"No activity yet for {acc['name']}. Check their setup to begin.")
            st.button("Check this customer's setup", on_click=_open_setup, args=(aid,), key="tl_setup", type="primary")
        else:
            st.info(f"No activity yet for {acc['name']}. There is no setup to check because they have not bought anything.")
        return
    keep = st.multiselect("Show activity from", list(ACTOR.values()), default=list(ACTOR.values()), key="tl_filter")
    shown = [i for i in items if ACTOR[i["actor"]] in keep]
    if not shown:
        st.caption("Nothing matches the selected filters.")
        return
    box = st.container(height=420) if len(shown) > 8 else st.container()
    with box:
        for i in shown:
            st.markdown(f"**{when(i['ts'])}** · {ACTOR[i['actor']]} — {_timeline_text(i)}")
        if any(i["origin"] == "seed" for i in shown):
            st.caption("Entries from before this session are sample history.")
