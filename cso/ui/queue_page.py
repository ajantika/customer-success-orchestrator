from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rules, services as S, session
from ..models import ASSIGNEES, PRODUCT_LABEL
from ..retrieval import get_retriever
from . import style

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
        session.flash("warning", str(e))
        return
    if res.get("outcome") == "error":
        session.report_run(res)
        return
    t = db.one("SELECT journey_id FROM human_tasks WHERE id=?", (tid,))
    j = db.one("SELECT state FROM journeys WHERE id=?", (t["journey_id"],))
    session.flash("success", f"Support task {tid} resolved. This is not the same as onboarding being completed. "
                             f"A fresh progress check ran and the journey is now: {j['state'].replace('_', ' ')}. {res['summary']}")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Human work queue")
    st.caption("Tasks created by the agent's handoffs. Resolving a task closes the support issue only; onboarding completion is decided from fresh product progress.")
    show = st.multiselect("Status", ["open", "assigned", "in_progress", "resolved"], default=["open", "assigned", "in_progress"])
    rows = db.q("SELECT t.*, a.name FROM human_tasks t JOIN accounts a ON a.id=t.account_id WHERE t.status IN (%s)" % ",".join("?" * len(show)), tuple(show)) if show else []
    rows.sort(key=lambda r: (PRIO[r["priority"]], r["created_at"]))
    if not rows:
        st.info("No tasks match. Ask the agent to escalate (reply “We already tried those steps”) or widen the status filter.")
        return
    st.dataframe(pd.DataFrame([{"Task": r["id"], "Account": r["name"], "Issue": r["issue"], "Priority": r["priority"], "Team": r["team"], "Status": r["status"],
                                "Assignee": r["assignee"] or "—", "Source": "Seeded" if r["origin"] == "seed" else "This session"} for r in rows]),
                 hide_index=True, width="stretch")
    tid = st.selectbox("Open task", [r["id"] for r in rows], format_func=lambda x: f"{x} · {next(r['name'] for r in rows if r['id'] == x)}")
    t = next(r for r in rows if r["id"] == tid)
    ctx = json.loads(t["context"] or "{}")
    st.markdown(f"### {t['id']} · {t['issue']}")
    st.markdown(f"**{t['name']}** · {PRODUCT_LABEL[t['product']]} · priority **{t['priority']}** · {t['team']} · status **{t['status']}**")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("**Customer goal**")
        st.write(ctx.get("goal") or db.one("SELECT goal FROM accounts WHERE id=?", (t["account_id"],))["goal"])
        st.markdown("**Agent summary**")
        st.write(ctx.get("summary", "—"))
        st.markdown("**Relevant product status (now)**")
        pr = rules.progress(db, t["account_id"], t["product"])
        st.markdown("  \n".join(f"{'✅' if m['done'] else '⬜'} {m['label']}" for m in pr["milestones"]))
        st.markdown("**Steps the customer says they tried**")
        titles = {c.doc_id: c.title for c in get_retriever().chunks}
        att = ctx.get("attempted_doc_ids", [])
        st.markdown("\n".join(f"- {d} · {titles.get(d, d)}" for d in att) if att else "_none recorded_")
    with c2:
        st.markdown("**Guidance previously sent**")
        g = ctx.get("guidance_sent", [])
        if g:
            for m in g:
                st.markdown(f"- `{m['id']}` ({m['channel']}, {m['ts'][:10]}) {m['excerpt'][:140]}… _{', '.join(m['docs'])}_")
        else:
            st.markdown("_none captured (seeded task)_")
        st.markdown("**Conversation references**")
        refs = ctx.get("conversation_refs", [])
        st.markdown("\n".join(f"- `{r['id']}` {r['from']} via {r['channel']}: {r['excerpt'][:100]}" for r in refs) if refs else "_none captured (seeded task)_")
    if t["status"] == "resolved":
        st.success(f"Resolved {t['resolved_at'][:16]}: {t['resolution_note']}")
        return
    st.divider()
    a, b = st.columns(2)
    with a:
        st.selectbox("Assignee", ASSIGNEES[t["team"]], key=f"as_{tid}")
        st.button("Assign", key=f"asb_{tid}", on_click=_assign, args=(db, tid))
        if t["status"] != "in_progress":
            st.button("Mark in progress", key=f"st_{tid}", on_click=_start, args=(db, tid))
    with b:
        st.text_area("Resolution note (required)", key=f"note_{tid}", height=90, placeholder="What was fixed and how it was verified")
        st.checkbox("Simulate: the fix unblocked the customer's next milestone (emits a synthetic product event)", key=f"fix_{tid}", value=True,
                    help="Demo helper. Without it, the fresh check finds no new progress and the journey simply resumes monitoring.")
        ok = len(st.session_state.get(f"note_{tid}", "").strip()) >= 10
        st.button("Resolve task", type="primary", key=f"res_{tid}", on_click=_resolve, args=(db, tid), disabled=not ok,
                  help=None if ok else "Enter a resolution note of at least 10 characters.")
