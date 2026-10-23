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
        session.flash("success", f"{tid} assigned to {st.session_state[f'as_{tid}']}.")
    except ValueError as e:
        session.flash("warning", str(e))


def _start(db, tid):
    S.set_task_status(db, tid, "in_progress")
    session.flash("success", f"{tid} marked in progress.")


def _resolve(db, tid):
    note = st.session_state.get(f"note_{tid}", "")
    try:
        res = S.resolve_task(db, tid, note, st.session_state.get(f"fix_{tid}", False), session.mode(), session.llm_settings())
    except ValueError as e:
        session.flash("warning", f"{e} Nothing was changed.")
        return
    if res.get("outcome") == "error":
        session.report_run(res)
        return
    t = db.one("SELECT journey_id FROM human_tasks WHERE id=?", (tid,))
    j = db.one("SELECT state FROM journeys WHERE id=?", (t["journey_id"],))
    d = narrate.from_run(db, res["run_id"]) if res.get("run_id") else {"found": [], "did": res["summary"], "why": ""}
    session.record_action("The support issue is resolved. The assistant will now check whether the customer has completed setup.", d["found"],
                          "Resolving a support issue is not the same as completing onboarding, so progress is verified from product events.", run_id=res.get("run_id"),
                          detail=f"{d['did']} The customer's journey is now “{style.STATE_LABEL_.get(j['state'], j['state'])}”.")


def _on_task():
    st.session_state["task"] = st.session_state.get("w_task")


def _back_to_journey(aid, prod):
    session.select(aid, prod)
    session.goto("agent")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Support tasks")
    sel = st.session_state.get("task")
    rows = db.q("SELECT t.*, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id WHERE t.status!='resolved' ORDER BY t.created_at")
    if sel and sel not in [r["id"] for r in rows]:  # a task opened from a link stays visible after it is resolved
        extra = db.one("SELECT t.*, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (sel,))
        if extra:
            rows.append(extra)
    rows.sort(key=lambda r: (PRIO[r["priority"]], r["created_at"]))
    if not rows:
        st.info("No support tasks yet. They appear when the assistant needs a person to investigate, for example after a customer says they already tried the suggested steps.")
        return
    ids = [r["id"] for r in rows]
    if sel not in ids:
        sel = ids[0]
        st.session_state["task"] = sel
    st.session_state["w_task"] = sel
    t = next(r for r in rows if r["id"] == sel)
    ctx = json.loads(t["context"] or "{}")
    if t["status"] == "resolved":
        session.show_action()
        st.success(f"Resolved {when(t['resolved_at'])}: {t['resolution_note']}")
        st.button("Return to this customer's journey", on_click=_back_to_journey, args=(t["account_id"], t["product"]), key="back_done", type="primary")
    else:
        st.markdown(f"### Support needs to investigate this issue.")
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
    with c3:
        st.markdown("**Who owns the next step**")
        st.write(f"{t['team']}" + (f" · {t['assignee']}" if t["assignee"] else " · not assigned yet"))
        st.caption(f"Priority {t['priority']} · {status(t['status'])}")
    if t["status"] != "resolved":
        with st.form(key=f"resolve_{sel}"):
            st.text_area("Resolution note (required)", key=f"note_{sel}", height=90, placeholder="What was fixed and how it was verified (at least 10 characters)")
            st.checkbox("Demo helper: pretend the fix unblocked the customer's next step", key=f"fix_{sel}", value=True,
                        help="Adds a sample product event. Without it, the fresh check finds no new progress and the journey simply resumes monitoring.")
            st.form_submit_button("Save note and resolve", type="primary", on_click=_resolve, args=(db, sel))
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
    with st.expander("Assign, update status, or choose a different task"):
        st.selectbox("Task", ids, format_func=lambda x: f"{x} · {next(r['name'] for r in rows if r['id'] == x)} · {status(next(r['status'] for r in rows if r['id'] == x))}", key="w_task", on_change=_on_task)
        if t["status"] != "resolved":
            st.selectbox("Assignee", ASSIGNEES[t["team"]], key=f"as_{sel}")
            st.button("Assign", key=f"asb_{sel}", on_click=_assign, args=(db, sel))
            if t["status"] != "in_progress":
                st.button("Mark in progress", key=f"st_{sel}", on_click=_start, args=(db, sel))
