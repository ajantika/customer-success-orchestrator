from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rules, session, team
from ..format import rec_status, status, when
from ..tools import DISMISS_REASONS, REVIEWERS
from .. import flags
from . import narrate, style, walkthroughs

NORTHSTAR_MEETING = "MTG-001"
ACTION_LABEL = {"training": "Learning recommendation", "technical_followup": "Technical follow-up first", "timing": "Timing: wait", "clarify": "Ask a clarifying question",
                "discovery": "Discovery conversation", "no_action": "No action"}


# ------------------------------------------------------------- callbacks ---
def _on_meeting():
    st.session_state["meeting"] = st.session_state.get("w_meeting")
    db = session.get_db()
    if team.latest_rec(db, st.session_state["meeting"]):
        team.view_brief(db, st.session_state["meeting"], st.session_state["reviewer"])


def _on_reviewer():
    st.session_state["reviewer"] = st.session_state["w_reviewer"]


def _prepare(db, mid):
    try:
        res = team.prepare_meeting_brief(db, mid, session.mode(), session.llm_settings())
        if res["outcome"] == "completed" and team.latest_rec(db, mid):
            team.view_brief(db, mid, st.session_state["reviewer"])
        session.report_run(res)
    except Exception as e:
        session.record_action(f"Something went wrong: {type(e).__name__}: {e}", tone="error")


def _scan(db):
    rows = team.scan_upcoming(db, 7)
    st.session_state["team_scan"] = rows
    new = sum(r["New recommendation"] == "Yes" for r in rows)
    session.record_action(f"Scanned {len(rows)} meeting(s) in the next 7 days and saved {new} new recommendation(s) for review. Nothing was sent to any customer.",
                          why="Scanning is an explicit action; nothing runs in the background. Running it again creates no duplicates.")


def _act(db, rec_id, action, reason=None, note=None, revised=None, defer_days=None):
    until = None
    if defer_days:
        from datetime import timedelta
        from ..db import to_iso
        until = to_iso(db.now() + timedelta(days=int(defer_days)))
    res = team.review(db, rec_id, action, st.session_state["reviewer"], reason, note, revised, until)
    if res["ok"]:
        extra = {"accepted": " Accepting means you agree it is worth raising. It was not sent to the customer and nobody was enrolled.",
                 "edited": " Your edit is saved next to the original, which is kept unchanged.", "discussed": " This records that you raised it. It does not mean the customer did anything.",
                 "dismissed": " The assistant will not suggest the same thing again for this meeting.", "deferred": " It stays saved and is not re-suggested until you revisit it.",
                 "reviewed": ""}[action]
        session.record_action(f"Recommendation {rec_id} is now **{status(action).lower()}**.{extra}", why=f"Recorded as {st.session_state['reviewer']}'s decision with the time and reason in the review history below. It also feeds the feedback summary and the Evaluation page.")
    else:
        session.record_action(res["error"]["message"], tone="warning")


def _edit(db, rec_id):
    revised = {"title": st.session_state[f"ed_title_{rec_id}"], "talking_point": st.session_state[f"ed_talk_{rec_id}"], "why_now": st.session_state[f"ed_why_{rec_id}"]}
    _act(db, rec_id, "edited", note=st.session_state.get(f"ed_note_{rec_id}") or None, revised=revised)


def _dismiss(db, rec_id):
    _act(db, rec_id, "dismissed", st.session_state.get(f"dr_{rec_id}"), st.session_state.get(f"dn_{rec_id}") or None)


def _defer(db, rec_id):
    _act(db, rec_id, "deferred", st.session_state.get(f"fr_{rec_id}"), None, None, st.session_state.get(f"fd_{rec_id}", 14))


def _learning(db, rec_id, stage):
    n = team.simulate_learning(db, rec_id, stage, 2)
    session.record_action(f"Synthetic update: {n} learner(s) {stage}. This is the customer's own progress, tracked separately from your decision." if n else "No learners could be updated for this step.",
                          why="Accepting a recommendation never enrols anyone. This button only simulates what a customer might do afterwards." if n else "", tone="success" if n else "info")


def _scenario(db):
    label = team.apply_scenario(db, st.session_state["scn"])
    st.session_state["meeting"] = team.NS_MEETING
    session.select(team.NORTHSTAR, "docs")
    session.record_action(f"Situation applied: {label}. Northstar's synthetic data was reshaped.", why="Click “Prepare meeting brief” to see how the assistant responds to this situation.", tone="info")


def _guided_edit(db, rec):
    """Demo helper: apply a small example edit, then accept, so both steps are recorded."""
    cur = json.loads(rec["content_current"])
    r1 = team.review(db, rec["id"], "edited", st.session_state["reviewer"], None, "Example edit added by the demo button.",
                     {"talking_point": cur["talking_point"] + " Who owns the shared documentation workflow on your side?"})
    r2 = team.review(db, rec["id"], "accepted", st.session_state["reviewer"]) if r1["ok"] else r1
    if r2["ok"]:
        session.record_action(f"Recommendation {rec['id']} was edited and then accepted: it now reads **Accepted with edits**. The original wording is kept next to your edit. "
                              "Accepting means you agree it is worth raising; nothing was sent to the customer and nobody was enrolled.",
                              why=f"Both steps are recorded as {st.session_state['reviewer']}'s decisions in the review history below, and feed the feedback summary.")
    else:
        session.record_action(r2["error"]["message"], tone="warning")


def _exit_guided():
    st.session_state.pop("guided", None)


# ----------------------------------------------------------------- pieces ---
def _steps(db):
    rec = team.latest_rec(db, NORTHSTAR_MEETING)
    fb = lambda a: db.one("SELECT COUNT(*) n FROM rec_feedback WHERE meeting_id=? AND action=?", (NORTHSTAR_MEETING, a))["n"] > 0
    role = "acting as the Account Team."
    need = None if rec else "Prepare the brief first (step 1)."
    return [
        dict(title="Prepare the meeting brief", why="The assistant gathers the meeting purpose, usage, learning progress and blockers, then saves one recommendation for you to review.", role=role,
             done=rec is not None, label="Prepare the brief", action=lambda: _prepare(db, NORTHSTAR_MEETING)),
        dict(title="Review the evidence", why="Read the recommendation, its sources and what is still unknown. Marking it reviewed records that a person looked at it.", role=role,
             done=fb("reviewed"), label="Mark as reviewed", action=lambda: _act(db, rec["id"], "reviewed") if rec else None, disabled_reason=need),
        dict(title="Edit the talking point, then accept", why="This demo button applies a small example edit to the talking point and then accepts the recommendation, so both steps are recorded. Normally you type your own edit under “Edit”.", role=role,
             done=fb("accepted"), label="Apply example edit and accept", action=lambda: _guided_edit(db, rec) if rec else None, disabled_reason=need),
        dict(title="Mark it discussed after the meeting", why="“Discussed” means you raised it with the customer. It is separate from anything the customer does.", role=role,
             done=fb("discussed"), label="Mark as discussed", action=lambda: _act(db, rec["id"], "discussed") if rec else None, disabled_reason=need),
        dict(title="See the customer's learning tracked separately", why="Accepting a recommendation never enrols anyone. This synthetic button shows what customer progress could look like afterwards.",
             role="simulating the customer's learning progress (synthetic).", done=db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] > 0,
             label="Simulate enrolment", action=lambda: _learning(db, rec["id"], "enrolled") if rec else None, disabled_reason=need),
    ]


def _signals(db, aid):
    subs = [r["product"] for r in db.q("SELECT product FROM subscriptions WHERE account_id=?", (aid,))]
    if not subs:
        st.info("This customer is evaluating the product and has no usage or learning data. Nothing has been assumed.")
        return
    prod = "docs" if "docs" in subs else subs[0]
    pr = rules.progress(db, aid, prod)
    c = st.columns(4)
    c[0].metric("Setup milestones", f"{pr['done_count']} of {pr['total']}", help="Product milestones completed.")
    c[1].metric("Shared-workflow activity", pr["workflow_recent"], help=f"Events in the last 14 days. The 30 days before had {pr['workflow_prior']}.")
    rows = db.q("SELECT course_id, status, COUNT(*) n FROM learner_records WHERE account_id=? GROUP BY course_id, status", (aid,))
    done = lambda cid: sum(r["n"] for r in rows if r["course_id"] == cid and r["status"] == "completed")
    c[2].metric("Intro training completed", done("CRS-101") if rows else "No data", help="Learners who completed Docs Fundamentals.")
    c[3].metric("Next module completed", done("CRS-102") if rows else "No data", help="Learners who completed Shared Documentation Workflows.")
    blockers = db.one("SELECT (SELECT COUNT(*) FROM support_cases WHERE account_id=? AND status='open') + (SELECT COUNT(*) FROM human_tasks WHERE account_id=? AND status!='resolved') n", (aid, aid))["n"]
    st.caption(f"Open technical items: {blockers}. Activity trend: {pr['workflow_recent']} in the last 14 days vs {pr['workflow_prior']} in the 30 days before (Docs).")


STATUS_NOTE = {
    "generated": "Review required. Nothing is shared with the customer, no one is enrolled and nothing is purchased by accepting this.",
    "reviewed": "Reviewed. Decide whether to accept, edit, dismiss or defer it. Nothing has been shared with the customer.",
    "edited": "Edited by the Account Team and awaiting acceptance. Nothing has been shared with the customer.",
    "accepted": "Accepted by the Account Team. It has not been sent to the customer and nobody has been enrolled. Mark it discussed after you raise it.",
    "discussed": "Discussed. This records that the Account Team raised it with the customer. It does not mean the customer did anything.",
    "deferred": "Deferred. It is saved and will not be suggested again unless you revisit it.",
    "dismissed": "Dismissed. The assistant will not suggest the same thing again for this meeting.",
    "withdrawn": "Withdrawn because the meeting was cancelled or moved. Prepare a new brief if needed.",
}


def _rec_card(db, rec, m):
    content = json.loads(rec["content_current"])
    original = json.loads(rec["content_original"])
    courses = json.loads(rec["courses"])
    evidence = json.loads(rec["evidence"])
    comp = json.loads(rec["completeness"] or "{}")
    with st.container(border=True):
        top = st.columns([3, 2])
        top[0].markdown(f"{style.badge(rec['status'], rec_status(rec))} &nbsp; <span class='cso-pill'>{ACTION_LABEL.get(rec['action_type'], rec['action_type'])}</span>", unsafe_allow_html=True)
        top[1].caption(f"Prepared {when(rec['created_at'])} · demo mode · {rec['id']}" if rec["generation_mode"] != "live" else f"Prepared {when(rec['created_at'])} · AI model · {rec['id']}")
        st.caption(STATUS_NOTE.get(rec["status"], ""))
        if rec["needs_refresh"]:
            st.warning("The meeting date changed after this was prepared. Click “Refresh the brief”.")
        st.markdown(f"**Why this needs attention.** {rec['why_now']}")
        st.markdown(f"**Recommended action.** {rec['title']}")
        st.markdown("**Suggested talking point**")
        st.markdown(f"> {rec['talking_point']}")
        _actions(db, rec)
        with st.expander("Supporting detail: signals, training options and what to confirm"):
            _signals(db, m["account_id"])
            if courses:
                st.markdown("**Training options**")
                for c in courses:
                    pre = ", ".join(c["prerequisites"]) or "none"
                    st.markdown(f"- **{c['title']}** ({c['course_id']}) · {'Paid' if c['paid'] else 'Free'} · {c['format']}, {c['duration_min']} minutes · prerequisites: {pre} · "
                                f"{c['learners_ready']} learner(s) ready" + (f", {c['learners_blocked']} need a prerequisite first" if c["learners_blocked"] else "") + f" · availability: {c['availability']}")
                    if c.get("free_alternatives_considered"):
                        st.caption(f"Free alternatives considered: {c['free_alternatives_considered']}")
            lg = json.loads(rec["learner_group"] or "{}").get("summary")
            if lg:
                st.markdown(f"**Learner group.** {lg}")
            unk = json.loads(rec["unknowns"] or "[]")
            if unk:
                st.markdown("**Important unknowns**\n" + "\n".join(f"- {u}" for u in unk))
            st.markdown("**Internal brief**")
            st.write(rec["brief"])
        with st.expander(f"Evidence and sources ({len(evidence)})"):
            if evidence:
                st.dataframe(pd.DataFrame([{"Evidence": e["label"], "Source": e["source"].replace("_", " ").capitalize(), "As of": when(e["ts"])} for e in evidence]), hide_index=True, width="stretch")
            if comp:
                st.markdown(f"**Evidence completeness:** {len(comp.get('have', []))} of {len(comp.get('have', [])) + len(comp.get('missing', []))} sources available."
                            + (f" Missing: {', '.join(comp['missing'])}." if comp.get("missing") else ""))
        hist = db.q("SELECT * FROM rec_feedback WHERE rec_id=? ORDER BY id", (rec["id"],))
        if hist or content != original:
            with st.expander(f"Review history ({len(hist)})"):
                if hist:
                    st.dataframe(pd.DataFrame([{"When": when(h["ts"]), "Reviewer": h["reviewer"], "Action": status(h["action"]), "Reason": h["reason"] or "", "Note": h["note"] or ""} for h in hist]), hide_index=True, width="stretch")
                if content != original:
                    st.markdown("**What changed (original vs current talking point)**")
                    a, b = st.columns(2)
                    a.markdown("**Original**"); a.write(original["talking_point"])
                    b.markdown("**Current**"); b.write(content["talking_point"])
        _outcomes(db, rec)


def _actions(db, rec):
    rid, st_ = rec["id"], rec["status"]
    if st_ in ("discussed", "withdrawn"):
        return
    if st_ == "dismissed":
        fb = db.one("SELECT reason FROM rec_feedback WHERE rec_id=? AND action='dismissed' ORDER BY id DESC LIMIT 1", (rid,))
        st.info(f"Dismissed ({(fb or {}).get('reason') or 'no reason recorded'}). The assistant will not recommend it again for this meeting.")
        return
    st.markdown("**Your review**")
    if st.session_state.get("guided") != "team":
        style.role_banner("acting as the Account Team.")
    st.caption("**Accept**: worth raising (nothing is sent or enrolled). **Edit**: change the wording; the original is kept. **Dismiss** / **Defer**: with a reason. **Mark discussed**: you raised it with the customer.")
    cols = st.columns(5)
    if st_ == "generated":
        cols[0].button("Mark reviewed", key=f"rv_{rid}", on_click=_act, args=(db, rid, "reviewed"), width="stretch")
    if st_ in ("generated", "reviewed", "deferred", "edited"):
        cols[1].button("Accept", key=f"ac_{rid}", type="primary", on_click=_act, args=(db, rid, "accepted"), width="stretch")
    if st_ in ("accepted", "edited"):
        cols[2].button("Mark discussed", key=f"di_{rid}", type="primary", on_click=_act, args=(db, rid, "discussed"), width="stretch")
    with st.expander("Edit"):
        cur = json.loads(rec["content_current"])
        st.text_input("Recommended next action", cur["title"], key=f"ed_title_{rid}")
        st.text_area("Why it matters now", cur["why_now"], key=f"ed_why_{rid}", height=90)
        st.text_area("Talking point", cur["talking_point"], key=f"ed_talk_{rid}", height=110)
        st.text_input("What did you change and why? (optional)", key=f"ed_note_{rid}")
        st.button("Save edit", key=f"ed_{rid}", on_click=_edit, args=(db, rid))
    if st_ in ("generated", "reviewed", "accepted", "edited", "deferred"):
        with st.expander("Dismiss"):
            st.selectbox("Reason (required)", DISMISS_REASONS, key=f"dr_{rid}")
            st.text_input("Note (optional)", key=f"dn_{rid}")
            st.button("Dismiss recommendation", key=f"dm_{rid}", on_click=_dismiss, args=(db, rid))
    if st_ in ("generated", "reviewed"):
        with st.expander("Defer"):
            st.selectbox("Reason (required)", DISMISS_REASONS, key=f"fr_{rid}")
            st.selectbox("Revisit in (days)", [7, 14, 30], index=1, key=f"fd_{rid}")
            st.button("Defer recommendation", key=f"df_{rid}", on_click=_defer, args=(db, rid))


def _outcomes(db, rec):
    if not json.loads(rec["courses"]):
        return
    st.markdown("**Customer learning outcomes (tracked separately)**")
    rows = db.q("SELECT stage, SUM(learner_count) n FROM learning_outcomes WHERE rec_id=? GROUP BY stage", (rec["id"],))
    got = {r["stage"]: r["n"] for r in rows}
    st.caption(f"Enrolled: {got.get('enrolled', 0)} · Started: {got.get('started', 0)} · Completed: {got.get('completed', 0)} learner(s). "
               "Accepting the recommendation does not change these numbers.")
    if rec["status"] in ("accepted", "edited", "discussed"):
        c = st.columns(3)
        for col, stage in zip(c, ("enrolled", "started", "completed")):
            col.button(f"Simulate: 2 learners {stage}", key=f"lo_{rec['id']}_{stage}", on_click=_learning, args=(db, rec["id"], stage), width="stretch")


# ------------------------------------------------------------------- page ---
def render():
    db = session.get_db()
    guided = st.session_state.get("guided") == "team"
    st.title("Meeting preparation" if guided else "Account Team Assistant")
    st.session_state.setdefault("reviewer", "Riley Chen")
    steps = _steps(db) if guided else None
    cur = walkthroughs.panel("team", steps) if guided else None
    if guided:
        st.session_state["meeting"] = NORTHSTAR_MEETING
        session.select("ACC-041", "docs")
    else:
        st.caption("For Account Executives and Solutions Architects preparing for a customer conversation. The assistant combines the customer's goal, product usage, "
                   "learning progress and training options into a brief. Every recommendation needs a human review.")
    st.session_state["w_reviewer"] = st.session_state["reviewer"]
    with st.expander("Reviewing as (synthetic identity)", expanded=False):
        st.selectbox("Reviewer", REVIEWERS, key="w_reviewer", on_change=_on_reviewer)
    session.show_flash()
    nxt = (steps[cur]["title"] + f" (you are {steps[cur]['role'].rstrip('.')})") if guided and cur is not None else (
        "Review the recommendation below." if not guided else "Read the summary below, then choose what to explore next.")
    session.show_action(nxt, compact=True)
    if guided and cur is None:
        walkthroughs.summary_team(db)

    meetings = db.q("SELECT m.*, a.name, a.lifecycle FROM meetings m JOIN accounts a ON a.id=m.account_id WHERE m.starts_at>=? AND m.starts_at<=? ORDER BY m.starts_at",
                    (team.to_iso(db.now() - team.timedelta(days=1)), team.to_iso(db.now() + team.timedelta(days=14))))
    if not meetings:
        st.info("No meetings in the next 14 days.")
        return
    recs = {m["id"]: team.latest_rec(db, m["id"]) for m in meetings}
    table = pd.DataFrame([{"Date": when(m["starts_at"]), "Customer": m["name"], "Owner": m["owner"], "Solutions architect": m["solutions_architect"], "Stage": (m["lifecycle"] or "").capitalize(),
                           "Purpose": m["purpose"], "Meeting": status(m["status"]), "Recommendation": status(recs[m["id"]]["status"]) if recs[m["id"]] else "Not prepared"} for m in meetings])
    cfg = {"Purpose": st.column_config.TextColumn(width="large"), "Customer": st.column_config.TextColumn(width="medium"), "Date": st.column_config.TextColumn(width="medium")}
    with st.expander("All upcoming meetings (simulated calendar, next 14 days)", expanded=not guided):
        c1, c2 = st.columns([4, 2])
        c1.caption("No real calendar or CRM connection. Click a meeting in the selector below to open its brief.")
        c2.button("Scan upcoming meetings", on_click=_scan, args=(db,), width="stretch", disabled=session.mode() == "live",
                  help="Prepares briefs for every scheduled meeting in the next 7 days. Nothing runs in the background; this is an explicit action." if session.mode() != "live"
                  else "Disabled with an AI model so one click cannot trigger many paid calls.")
        st.dataframe(table, hide_index=True, width="stretch", height=min(380, 40 + 36 * len(meetings)), column_config=cfg)
        if st.session_state.get("team_scan"):
            st.markdown("**Last scan**")
            st.dataframe(pd.DataFrame(st.session_state["team_scan"]).drop(columns=["meeting_id"]).assign(Date=lambda d: d["Date"].map(when)), hide_index=True, width="stretch")
        ids = [m["id"] for m in meetings]
        sel = st.session_state.get("meeting")
        if sel not in ids:
            sel = ids[0]
            st.session_state["meeting"] = sel
        st.session_state["w_meeting"] = sel
        names = {m["id"]: f"{when(m['starts_at'], False)} · {m['name']} · {m['purpose'][:60]}" for m in meetings}
        if not guided:
            st.selectbox("Meeting", ids, format_func=names.get, key="w_meeting", on_change=_on_meeting)
    sel = st.session_state.get("meeting") if st.session_state.get("meeting") in [m["id"] for m in meetings] else meetings[0]["id"]
    m = next(x for x in meetings if x["id"] == sel)
    session.select(m["account_id"])
    roles = ", ".join(json.loads(m["attendee_roles"]))

    st.markdown(f"## {m['name']}")
    st.markdown(f"{style.badge(m['status'])} &nbsp; <span class='cso-pill'>{(m['lifecycle'] or '').capitalize()} stage</span> <span class='cso-pill'>Owner: {m['owner']}</span> "
                f"<span class='cso-pill'>Solutions architect: {m['solutions_architect']}</span>", unsafe_allow_html=True)
    acc = db.one("SELECT goal FROM accounts WHERE id=?", (m["account_id"],))
    st.markdown(f"**Meeting:** {when(m['starts_at'])} · {m['purpose']}  \n**Attendees:** {roles}  \n**Customer goal.** {acc['goal'] or 'Not recorded'}")
    if m["previous_start"]:
        st.caption(f"Moved from {when(m['previous_start'])}.")

    if m["status"] != "scheduled":
        st.warning("This meeting is cancelled. Pending recommendations were withdrawn and no new meeting-specific prompts are created. Use “Try other situations” to put it back.")
    if not guided or recs.get(sel) is None:
        style.role_banner("acting as the Account Team.")
        st.button("Prepare meeting brief", type="primary", on_click=_prepare, args=(db, sel), disabled=m["status"] != "scheduled", key="prep_main",
                  help="The assistant gathers evidence with its tools and saves a recommendation for your review. Nothing is sent to the customer."
                  if m["status"] == "scheduled" else "The meeting is cancelled, so no brief can be prepared.")
    elif not guided:
        st.button("Refresh the brief", on_click=_prepare, args=(db, sel), key="prep_again")
    rec = recs.get(sel)
    if rec:
        _rec_card(db, rec, m)
    else:
        st.info("No brief yet. Click “Prepare meeting brief”.")
        with st.expander("Account signals the assistant will use"):
            _signals(db, m["account_id"])
    if flags.advanced():
        with st.expander("Reviewer option: try other situations (changes Northstar Retail's synthetic data)"):
            st.caption("Each choice reshapes Northstar's data, then you click “Prepare meeting brief” to see the assistant respond. “Restart this walkthrough” restores the original.")
            st.selectbox("Situation", list(team.SCENARIOS), format_func=team.SCENARIOS.get, key="scn")
            st.button("Apply situation", on_click=_scenario, args=(db,))
    with st.expander("Feedback summary (what reviewers are telling the product team)"):
        fs = team.feedback_summary(db)
        st.caption("Includes synthetic history. Use it to decide what to build or fix; the assistant does not learn from it automatically.")
        a, b = st.columns(2)
        a.markdown("**Dismissal and deferral reasons**")
        a.dataframe(pd.DataFrame(fs["reasons"]).rename(columns={"reason": "Reason", "n": "Count"}) if fs["reasons"] else pd.DataFrame({"Reason": []}), hide_index=True, width="stretch")
        b.markdown("**Recommendations that were edited**")
        b.dataframe(pd.DataFrame(fs["edited"]).rename(columns={"action_type": "Type", "title": "Recommendation", "n": "Edits"}) if fs["edited"] else pd.DataFrame({"Recommendation": []}), hide_index=True, width="stretch")
        st.markdown(f"**Accepted but not yet discussed:** {len(fs['accepted_not_discussed'])}")
        st.markdown("**Repeated information gaps:** " + ("; ".join(f"{g['gap']} ({g['n']})" for g in fs["gaps"]) if fs["gaps"] else "none yet"))
