from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rules, services as S, session
from ..format import status, when
from ..models import ASSIGNEES, PRODUCT_LABEL
from ..retrieval import get_retriever
from . import narrate, style

PRIO = {"high": 0, "medium": 1, "low": 2}


def _assign(db, tid):
    try:
        S.assign_task(db, tid, st.session_state[f"as_{tid}"])
        session.record_action(f"{tid} was assigned to {st.session_state[f'as_{tid}']}.", tone="success", scope=("queue",))
    except ValueError as e:
        session.record_action(str(e), tone="warning", scope=("queue",))


def _start(db, tid):
    S.set_task_status(db, tid, "in_progress")
    session.record_action(f"{tid} is now in progress.", tone="success", scope=("queue",))


def _resolve(db, tid):
    note = st.session_state.get(f"note_{tid}", "")
    t = db.one("SELECT t.journey_id, t.account_id, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (tid,))
    if len((note or "").strip()) < 10:
        st.session_state[f"err_{tid}"] = "Please describe what was fixed and how you checked it (at least 10 characters). Your text is kept."
        return
    st.session_state.pop(f"err_{tid}", None)
    try:
        res = S.resolve_task(db, tid, note, st.session_state.get(f"fix_{tid}", False), session.mode(), session.llm_settings())
    except ValueError as e:
        st.session_state[f"err_{tid}"] = str(e)
        return
    if res.get("outcome") == "error":
        session.report_run(res)
        return
    j = db.one("SELECT state FROM journeys WHERE id=?", (t["journey_id"],))
    d = narrate.from_run(db, res["run_id"]) if res.get("run_id") else {"found": [], "did": res["summary"], "why": ""}
    session.record_action(f"The support issue for {t['name']} is resolved. The assistant will now check whether the customer has completed setup.", d["found"],
                          "Resolving a support issue is not the same as completing onboarding, so progress is verified from product events.", run_id=res.get("run_id"),
                          detail=f"{d['did']} The customer's journey is now “{style.STATE_LABEL_.get(j['state'], j['state'])}”.", scope=("queue", "agent"), account_id=t["account_id"])


def _on_task():
    st.session_state["task"] = st.session_state.get("w_task")


def _setup(aid, prod):
    session.select(aid, prod)
    session.goto("agent")


def _scope(value):
    st.session_state["queue_scope"] = value
    st.session_state.pop("task", None)


def _task_label(r):
    return f"{r['id']} · {r['name']} · {PRODUCT_LABEL[r['product']]} · {status(r['status'])}"


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Support tasks")
    aid, prod = st.session_state.get("acct"), st.session_state.get("prod")
    scope = st.session_state.get("queue_scope", "customer")
    q = "SELECT t.*, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id"
    if scope == "all":
        rows = db.q(q + " ORDER BY t.status='resolved', t.created_at")
        rows.sort(key=lambda r: (r["status"] == "resolved", PRIO[r["priority"]], r["created_at"]))
        st.markdown("**Showing every customer's support tasks.**")
        if aid:
            name = db.one("SELECT name FROM accounts WHERE id=?", (aid,))["name"]
            st.button(f"Show only {name}'s support tasks", on_click=_scope, args=("customer",), key="to_customer")
    else:
        if not aid:
            st.info("Choose a customer in the Customer workspace to see their support tasks, or view everyone's.")
            st.button("View all support tasks", on_click=_scope, args=("all",), key="all_a")
            return
        rows = db.q(q + " WHERE t.account_id=? ORDER BY t.status='resolved', t.created_at", (aid,))
        name = db.one("SELECT name FROM accounts WHERE id=?", (aid,))["name"]
        style.context_line(db, aid, prod)
        if not rows:
            st.info(f"No support tasks for {name}.")
            c = st.columns(2)
            c[0].button(f"Back to {name}'s setup", on_click=_setup, args=(aid, prod), key="back_none", width="stretch")
            c[1].button("View all support tasks", on_click=_scope, args=("all",), key="all_b", width="stretch")
            return
        st.button("View all support tasks", on_click=_scope, args=("all",), key="all_c", help="Shows every customer's tasks instead of only this customer's.")
    if not rows:
        st.info("No support tasks yet.")
        return
    ids = [r["id"] for r in rows]
    sel = st.session_state.get("task")
    if sel not in ids:
        sel = next((r["id"] for r in rows if r["status"] != "resolved"), ids[0])
        st.session_state["task"] = sel
    if len(rows) > 1:
        st.session_state["w_task"] = sel
        st.selectbox("Support task", ids, format_func=lambda x: _task_label(next(r for r in rows if r["id"] == x)), key="w_task", on_change=_on_task)
    t = next(r for r in rows if r["id"] == sel)
    ctx = json.loads(t["context"] or "{}")
    if scope == "all":
        style.context_line(db, t["account_id"], t["product"])
    session.show_action("queue", any_customer=(scope == "all"))
    if t["status"] == "resolved":
        st.success(f"Resolved {when(t['resolved_at'])}: {t['resolution_note']}")
        pr = rules.progress(db, t["account_id"], t["product"])
        nxt = f"Next step: {pr['next_milestone']['customer_label']}." if pr["next_milestone"] else "Setup is complete."
        st.markdown(f"**Task status: Resolved.** {nxt}")
        st.button(f"Continue {t['name']}'s setup", on_click=_setup, args=(t["account_id"], t["product"]), key="cont_setup", type="primary")
    else:
        st.markdown("### Support needs to investigate this issue.")
        st.markdown(f"**Task status: {status(t['status'])}**")
        if st.session_state.get("guided") == "onboarding":
            st.caption("Record how the issue was resolved below. The assistant will then check Maple's setup again.")
    titles = {c.doc_id: c.title for c in get_retriever().chunks}
    att = ctx.get("attempted_doc_ids", [])
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        st.markdown("**The problem**")
        st.write(f"{t['name']} · {PRODUCT_LABEL[t['product']]}: {t['issue'].split(': ', 1)[-1]}")
        st.caption(f"Customer goal: {ctx.get('goal') or db.one('SELECT goal FROM accounts WHERE id=?', (t['account_id'],))['goal']}")
    with c2:
        st.markdown("**What has already been tried**")
        st.markdown("\n".join(f"- {titles.get(d, d)}" for d in att) if att else "- No steps recorded")
        g = ctx.get("guidance_sent", [])
        if g:
            st.caption(f"The assistant sent {len(g)} message(s) with guidance before this.")
        for f in ctx.get("follow_ups", []):
            st.caption(f"New message from the customer ({when(f['ts'])}): “{f['excerpt'][:100]}”")
    with c3:
        st.markdown("**Who owns the next step**")
        st.write(f"{t['team']}" + (f" · {t['assignee']}" if t["assignee"] else " · not assigned yet"))
        st.caption(f"Priority {t['priority']} · {status(t['status'])}")
    if t["status"] != "resolved":
        with st.form(key=f"resolve_{sel}"):
            st.text_area("What was fixed?", key=f"note_{sel}", height=90, placeholder="Reconnected the employee directory and confirmed the connection works.")
            if st.session_state.get(f"err_{sel}"):
                st.error(st.session_state[f"err_{sel}"])
            st.checkbox("Simulate that this fix completed the blocked setup step.", key=f"fix_{sel}", value=True,
                        help="This updates sample progress; it does not fix real software.")
            st.caption("Describe the fix and how you checked it worked. This helps the assistant continue supporting the customer.")
            st.form_submit_button("Save note and mark resolved", type="primary", on_click=_resolve, args=(db, sel))
        st.button(f"Back to {t['name']}'s setup", on_click=_setup, args=(t["account_id"], t["product"]), key="back_setup", help="Does not resolve the task or change any progress.")
        st.caption("Resolving the support issue is separate from completing onboarding. The assistant checks setup again afterwards.")
    with st.expander("More detail"):
        st.markdown("**Setup status (now)**")
        pr = rules.progress(db, t["account_id"], t["product"])
        st.markdown("  \n".join(f"{'✅' if m['done'] else '⬜'} {m['customer_label']}" for m in pr["milestones"]))
        st.markdown("**Summary written by the assistant**")
        st.write(ctx.get("summary", "—"))
        for m in ctx.get("guidance_sent", []):
            body = m["excerpt"].split("\n\n", 1)[-1] if m["excerpt"].startswith("Subject:") else m["excerpt"]
            st.markdown(f"- {m['channel'].capitalize()}, {when(m['ts'], False)}: {body[:140].strip()}… _{', '.join(m['docs'])}_")
        st.caption("Message IDs: " + (", ".join(r["id"] for r in ctx.get("conversation_refs", [])) or "none recorded"))
    if t["status"] != "resolved":
        with st.expander("Assign or update this task"):
            st.selectbox("Assignee", ASSIGNEES[t["team"]], key=f"as_{sel}")
            st.button("Assign", key=f"asb_{sel}", on_click=_assign, args=(db, sel))
            if t["status"] != "in_progress":
                st.button("Mark in progress", key=f"st_{sel}", on_click=_start, args=(db, sel))
