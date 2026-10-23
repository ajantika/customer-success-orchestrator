"""Shared guided-walkthrough panel and completion summaries for both workflows."""
from __future__ import annotations

import json

import streamlit as st

from .. import session, team
from ..db import DB
from ..format import rec_status, status, when
from ..models import STATE_LABEL
from ..restart import WORKFLOWS, restart_workflow
from . import style

INFO = {
    "onboarding": {
        "title": "Help a customer get started", "minutes": 5, "customer": "Maple Design",
        "intro": "Maple Design is an example company using the software. Jordan is its administrator and needs help completing setup. "
                 "Choose Jordan's replies below to see what happens next.",
    },
    "team": {
        "title": "Prepare for a customer conversation", "minutes": 4, "customer": "Northstar Retail",
        "intro": "You have a conversation with Northstar Retail tomorrow. Review what they want to achieve and the suggested next step.",
    },
}


def _restart(which):
    msg = restart_workflow(session.get_db(), which)
    st.session_state["guided"] = which
    for k in ("last_action", "sel_run", "_latest_run", "reply_text", "team_scan", "flash"):
        st.session_state.pop(k, None)
    session.select(WORKFLOWS[which][0], "docs", **({"meeting": "MTG-001"} if which == "team" else {}))
    session.flash("info", msg)


def _leave():
    st.session_state.pop("guided", None)
    session.goto("overview")


def _other(which):
    session.start_team_demo() if which == "onboarding" else session.start_onboarding_demo()


def _go(page):
    session.goto(page)


def restart_popover(which: str, key: str):
    name = WORKFLOWS[which][1]
    with st.popover("Restart this walkthrough"):
        st.markdown(f"This resets **{name}** only: its messages, tasks, recommendations and journey. "
                    f"{'Northstar Retail' if which == 'onboarding' else 'Maple Design'} keeps its progress. The demo clock returns to the original demo date.")
        st.button(f"Yes, restart {name}", key=f"rs_{key}", on_click=_restart, args=(which,), type="primary")


def panel(which: str, steps: list[dict]):
    """steps: dict(title, prompt, done, label, action, helper?, disabled_reason?). One prominent button per step."""
    info = INFO[which]
    done = [x["done"] for x in steps]
    cur = next((i for i, d in enumerate(done) if not d), None)
    with st.container(border=True):
        top = st.columns([4, 2])
        top[0].markdown(f"**{info['customer']}** · about {info['minutes']} minutes")
        top[1].button("Back to overview", key=f"back_{which}", on_click=_leave, width="stretch")
        if sum(done) == 0:
            st.markdown(info["intro"])
        else:
            with st.expander("About this example"):
                st.markdown(info["intro"])
        if cur is None:
            st.progress(1.0, text=f"Finished · {len(steps)} of {len(steps)} steps")
            return None
        x = steps[cur]
        st.progress(sum(done) / len(steps), text=f"Step {cur + 1} of {len(steps)}: {x['title']}")
        st.markdown(x["prompt"])
        blocked = x.get("disabled_reason")
        st.button(x["label"], key=f"g_{which}_{cur}", type="primary", on_click=x["action"], width="stretch", disabled=bool(blocked))
        if blocked:
            st.caption(blocked)
        elif x.get("helper"):
            st.caption(x["helper"])
        restart_popover(which, f"{which}_{cur}")
    return cur


# ----------------------------------------------------------- completion ---
def _next_steps(which: str):
    st.markdown("**What next?**")
    c = st.columns(3)
    other = "prepare for a customer conversation" if which == "onboarding" else "help a customer get started"
    c[0].button(f"Explore the other walkthrough: {other}", key=f"oth_{which}", on_click=_other, args=(which,), width="stretch")
    c[1].button("View activity and evaluation", key=f"ev_{which}", on_click=_go, args=("eval",), width="stretch")
    c[2].button("Restart this walkthrough", key=f"rst_{which}", on_click=_restart, args=(which,), width="stretch")
    st.caption("Exploring the other walkthrough keeps this one's results. Restarting resets only this example customer.")


def summary_onboarding(db: DB):
    aid = "ACC-001"
    j = db.one("SELECT * FROM journeys WHERE account_id=? AND product='docs'", (aid,))
    msgs = db.q("SELECT signals FROM interactions WHERE account_id=? AND actor='agent' AND kind='message' AND origin='session'", (aid,))
    kinds = [json.loads(m["signals"]).get("message_kind") for m in msgs]
    task = db.one("SELECT * FROM human_tasks WHERE account_id=? AND origin='session' ORDER BY id DESC LIMIT 1", (aid,))
    events = db.q("SELECT DISTINCT event_type FROM product_events WHERE account_id=? AND product='docs' AND origin='session' AND event_type!='usage_session'", (aid,))
    cancelled = db.one("SELECT COUNT(*) n FROM scheduled_actions WHERE account_id=? AND status='cancelled' AND origin='session'", (aid,))["n"]
    complete = j["state"] == "completed"
    support = db.one("SELECT planned_start FROM rollout_plans WHERE account_id=? AND product='support'", (aid,))
    open_tasks = db.q("SELECT id FROM human_tasks WHERE account_id=? AND status!='resolved'", (aid,))
    with st.container(border=True):
        st.markdown("### Summary: " + ("Docs setup verified complete" if complete else "Docs setup is not complete yet"))
        st.markdown("**The situation.** Maple's Docs setup stalled at connecting the employee directory.")
        clarified = db.one("SELECT COUNT(*) n FROM interactions WHERE account_id=? AND actor='agent' AND origin='session' AND json_extract(signals,'$.topic')='clarify'", (aid,))["n"] > 0
        acts = [f"The assistant sent {len(msgs)} message(s)" + (", asking which error the customer saw before sending only the matching fix." if clarified else ".")]
        if task:
            acts.append(f"When the steps did not work it created support task {task['id']} for {task['team']} and paused setup reminders."
                        + (f" Support resolved it: “{task['resolution_note'].rstrip('.')}”." if task["status"] == "resolved" else ""))
        if events:
            acts.append("Sample product events (created by the demo button) arrived for: " + ", ".join(e["event_type"].replace("_", " ") for e in events) + ". The assistant checked them before closing the journey.")
        if cancelled:
            acts.append(f"{cancelled} pending reminder(s) were cancelled.")
        st.markdown("**Actions taken**\n" + "\n".join(f"- {a}" for a in acts))
        st.markdown(f"**Resulting state.** Docs journey: **{STATE_LABEL[j['state']]}**. " + ("Completion was verified from product events, not from the customer's word alone." if complete else "Completion has not been verified."))
        st.markdown("**Still to do.** " + (f"Open tasks: {', '.join(t['id'] for t in open_tasks)}. " if open_tasks else "No open support tasks. ")
                    + f"Support rolls out on {when(support['planned_start'], False)}; no outreach was sent for it, as the rules require.")
    _next_steps("onboarding")


def summary_team(db: DB):
    rec = team.latest_rec(db, "MTG-001")
    hist = db.q("SELECT * FROM rec_feedback WHERE meeting_id='MTG-001' AND origin='session' ORDER BY id")
    lo = db.q("SELECT stage, SUM(learner_count) n FROM learning_outcomes WHERE origin='session' GROUP BY stage")
    with st.container(border=True):
        st.markdown("### Summary: recommendation reviewed and discussed" if rec and rec["status"] == "discussed" else "### Summary: recommendation in progress")
        st.markdown("**The situation.** Northstar wants several teams to use a shared documentation workflow. Activity has dropped and only two of six staff who finished intro training completed the next module.")
        if rec:
            acts = [f"The assistant gathered the meeting, usage, learning, blocker and catalog evidence and saved recommendation {rec['id']}: “{rec['title']}”."]
            edited = rec["content_current"] != rec["content_original"]
            acts += [f"{h['reviewer']} marked it **{status(h['action']).lower()}**" + (" (with edits)" if h["action"] == "accepted" and edited else "") + (f" ({h['reason']})" if h["reason"] else "") + "." for h in hist]
            st.markdown("**Actions taken**\n" + "\n".join(f"- {a}" for a in acts))
            st.markdown(f"**Resulting state.** Recommendation: **{rec_status(rec)}**. Nothing was sent to the customer and no one was enrolled by this decision.")
            got = {r["stage"]: r["n"] for r in lo}
            st.markdown(f"**Customer learning (tracked separately, sample data).** Enrolled: {got.get('enrolled', 0)}, started: {got.get('started', 0)}, completed: {got.get('completed', 0)}. "
                        "Whether the conversation or training improves adoption is not known from this demonstration.")
            st.markdown("**Still to do.** Confirm with the customer whether the team needs help applying the workflow, and who owns it. The customer decides about any training.")
    _next_steps("team")
