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
    session.record_action(f"Support task {tid} is resolved and the note is saved. The assistant then re-checked the customer's real progress and the journey is now “{style.STATE_LABEL_.get(j['state'], j['state'])}”. {d['did']}",
                          d["found"], "Resolving a support task is not the same as onboarding being complete, so progress was verified from product events first.", run_id=res.get("run_id"))


def _on_task():
    st.session_state["task"] = st.session_state.get("w_task")


def _back_to_journey(aid, prod):
    session.select(aid, prod)
    session.goto("agent")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Support tasks")
    st.caption("Tasks the assistant created when it could not solve a problem. Resolving a task closes the support issue only; onboarding completion is decided from fresh product progress.")
    style.role_banner("acting as the support specialist.")
    if st.session_state.get("guided") == "onboarding":
        st.info("**Walkthrough, step 5 of 6.** Write a short resolution note below (for example, “Re-issued the directory token and verified sync”) and click **Resolve task**. "
                "The assistant will then re-check Maple's real progress. Afterwards use **Return to this customer's journey**.")
    show = st.multiselect("Status", ["open", "assigned", "in_progress", "resolved"], default=["open", "assigned", "in_progress"], format_func=status)
    sel = st.session_state.get("task")
    rows = db.q("SELECT t.*, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id WHERE t.status IN (%s)" % ",".join("?" * len(show)), tuple(show)) if show else []
    if sel and sel not in [r["id"] for r in rows]:  # a task opened from a handoff link stays visible even if the filter would hide it
        extra = db.one("SELECT t.*, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (sel,))
        if extra:
            rows.append(extra)
    rows.sort(key=lambda r: (PRIO[r["priority"]], r["created_at"]))
    if not rows:
        st.info("No tasks match. Ask the agent to escalate (reply “We already tried those steps”) or widen the status filter.")
        return
    st.dataframe(pd.DataFrame([{"Task": r["id"], "Customer": r["name"], "Issue": r["issue"], "Priority": r["priority"].capitalize(), "Team": r["team"], "Status": status(r["status"]),
                                "Assignee": r["assignee"] or "Not assigned", "Source": "Seeded" if r["origin"] == "seed" else "This session"} for r in rows]),
                 hide_index=True, width="stretch")
    ids = [r["id"] for r in rows]
    if sel not in ids:
        sel = ids[0]
        st.session_state["task"] = sel
    st.session_state["w_task"] = sel
    names = {r["id"]: f"{r['id']} · {r['name']}" for r in rows}
    st.selectbox("Open task", ids, format_func=names.get, key="w_task", on_change=_on_task)
    t = next(r for r in rows if r["id"] == sel)
    ctx = json.loads(t["context"] or "{}")
    with st.container(border=True):
        c1, c2 = st.columns([4, 2])
        c1.markdown(f"**Customer:** {t['name']} · **Product:** {PRODUCT_LABEL[t['product']]} · **Task:** {t['id']}")
        c2.button("Open this customer's journey", on_click=_back_to_journey, args=(t["account_id"], t["product"]), key="back_top", width="stretch")
    st.markdown(f"### {t['issue']}")
    st.markdown(f"Priority **{t['priority']}** · {t['team']} · status **{status(t['status'])}**")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Customer goal**")
        st.write(ctx.get("goal") or db.one("SELECT goal FROM accounts WHERE id=?", (t["account_id"],))["goal"])
        st.markdown("**Agent summary**")
        st.write(ctx.get("summary", "—"))
        st.markdown("**Relevant product status (now)**")
        pr = rules.progress(db, t["account_id"], t["product"])
        st.markdown("  \n".join(f"{'✅' if m['done'] else '⬜'} {m['customer_label']}" for m in pr["milestones"]))
        st.markdown("**Steps the customer says they tried**")
        titles = {c.doc_id: c.title for c in get_retriever().chunks}
        att = ctx.get("attempted_doc_ids", [])
        st.markdown("\n".join(f"- {titles.get(d, d)} ({d})" for d in att) if att else "_none recorded_")
    with c2:
        st.markdown("**Guidance previously sent**")
        g = ctx.get("guidance_sent", [])
        if g:
            for m in g:
                body = m["excerpt"].split("\n\n", 1)[-1] if m["excerpt"].startswith("Subject:") else m["excerpt"]
                st.markdown(f"- {m['channel'].capitalize()}, {when(m['ts'], False)}: {body[:140].strip()}… _{', '.join(m['docs'])}_")
        else:
            st.markdown("_none captured (seeded task)_")
        with st.expander("Conversation references (message IDs)"):
            refs = ctx.get("conversation_refs", [])
            st.markdown("\n".join(f"- `{r['id']}` {r['from']} via {r['channel']}: {r['excerpt'][:100]}" for r in refs) if refs else "_none captured (seeded task)_")
    if t["status"] == "resolved":
        session.show_action("Return to the customer's journey to see the result.")
        st.success(f"Resolved {when(t['resolved_at'])}: {t['resolution_note']}")
        st.button("Return to this customer's journey", on_click=_back_to_journey, args=(t["account_id"], t["product"]), key="back_done", type="primary")
        return
    st.divider()
    a, b = st.columns(2)
    with a:
        st.selectbox("Assignee", ASSIGNEES[t["team"]], key=f"as_{sel}")
        st.button("Assign", key=f"asb_{sel}", on_click=_assign, args=(db, sel))
        if t["status"] != "in_progress":
            st.button("Mark in progress", key=f"st_{sel}", on_click=_start, args=(db, sel))
    with b:
        with st.form(key=f"resolve_{sel}"):
            st.text_area("Resolution note (required)", key=f"note_{sel}", height=90, placeholder="What was fixed and how it was verified (at least 10 characters)")
            st.checkbox("Demo helper: pretend the fix unblocked the customer's next step", key=f"fix_{sel}", value=True,
                        help="Creates a sample product event. Without it, the fresh check finds no new progress and the journey simply resumes monitoring.")
            st.form_submit_button("Save note and resolve", type="primary", on_click=_resolve, args=(db, sel))
