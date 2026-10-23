from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rules, session, team
from ..format import status, when
from ..tools import DISMISS_REASONS, REVIEWERS
from . import style

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
        session.flash("error", f"Something went wrong: {type(e).__name__}: {e}")


def _scan(db):
    rows = team.scan_upcoming(db, 7)
    st.session_state["team_scan"] = rows
    new = sum(r["New recommendation"] == "Yes" for r in rows)
    session.flash("success", f"Scanned {len(rows)} meeting(s) in the next 7 days: {new} new recommendation(s) for review. Nothing was sent to any customer.")


def _act(db, rec_id, action, reason=None, note=None, revised=None, defer_days=None):
    until = None
    if defer_days:
        from datetime import timedelta
        from ..db import to_iso
        until = to_iso(db.now() + timedelta(days=int(defer_days)))
    res = team.review(db, rec_id, action, st.session_state["reviewer"], reason, note, revised, until)
    if res["ok"]:
        session.flash("success", f"Recommendation {rec_id} marked {status(action).lower()}." + (" Accepting it does not enroll anyone or promise anything to the customer." if action == "accepted" else ""))
    else:
        session.flash("warning", res["error"]["message"])


def _edit(db, rec_id):
    revised = {"title": st.session_state[f"ed_title_{rec_id}"], "talking_point": st.session_state[f"ed_talk_{rec_id}"], "why_now": st.session_state[f"ed_why_{rec_id}"]}
    _act(db, rec_id, "edited", note=st.session_state.get(f"ed_note_{rec_id}") or None, revised=revised)


def _dismiss(db, rec_id):
    _act(db, rec_id, "dismissed", st.session_state.get(f"dr_{rec_id}"), st.session_state.get(f"dn_{rec_id}") or None)


def _defer(db, rec_id):
    _act(db, rec_id, "deferred", st.session_state.get(f"fr_{rec_id}"), None, None, st.session_state.get(f"fd_{rec_id}", 14))


def _learning(db, rec_id, stage):
    n = team.simulate_learning(db, rec_id, stage, 2)
    session.flash("success" if n else "info", f"Synthetic update: {n} learner(s) {stage}. This is the customer's progress, tracked separately from the Account Team's decision." if n else "No learners could be updated.")


def _scenario(db):
    label = team.apply_scenario(db, st.session_state["scn"])
    st.session_state["meeting"] = team.NS_MEETING
    session.select(team.NORTHSTAR, "docs")
    session.flash("info", f"Scenario applied: {label}. Click “Prepare meeting brief” to see how the assistant responds.")


def _guided_edit(db, rec):
    cur = json.loads(rec["content_current"])
    _act(db, rec["id"], "edited", note="Added a question about ownership.",
         revised={"talking_point": cur["talking_point"] + " Also ask who owns the shared documentation workflow on the customer side."})


def _exit_guided():
    st.session_state.pop("guided", None)


# ----------------------------------------------------------------- pieces ---
def _guided(db):
    rec = team.latest_rec(db, NORTHSTAR_MEETING)
    fb = lambda a: db.one("SELECT COUNT(*) n FROM rec_feedback WHERE meeting_id=? AND action=?", (NORTHSTAR_MEETING, a))["n"] > 0
    steps = [
        ("Prepare the meeting brief", "The assistant gathers the meeting purpose, usage, learning progress and blockers, then saves a recommendation for review.", rec is not None,
         "Prepare brief", lambda: _prepare(db, NORTHSTAR_MEETING)),
        ("Review the evidence", "Check what the recommendation is based on, and what is still unknown.", fb("reviewed"),
         "Mark reviewed", lambda: _act(db, rec["id"], "reviewed") if rec else None),
        ("Edit the talking point and accept", "Your edit is saved next to the original so a product owner can see what changed.", fb("edited") or fb("accepted"),
         "Edit and accept", lambda: _guided_edit(db, rec) if rec else None),
        ("Mark as discussed after the meeting", "Discussed is separate from the customer enrolling in anything.", fb("discussed"),
         "Mark discussed", lambda: _act(db, rec["id"], "discussed") if rec else None),
        ("Record the customer's learning separately", "Accepting a recommendation never enrolls anyone. This synthetic update shows the customer's own progress.",
         db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] > 0, "Simulate enrolment", lambda: _learning(db, rec["id"], "enrolled") if rec else None),
    ]
    cur = next((i for i, s in enumerate(steps) if not s[2]), None)
    with st.container(border=True):
        if cur is None:
            st.progress(1.0, text="Guided demo complete · 5 of 5 steps")
            st.success("The recommendation went from generated to discussed with a human in the loop. Try “Try other situations” below, or open the Evaluation page.")
        else:
            title, why, _, label, action = steps[cur]
            st.progress(sum(s[2] for s in steps) / len(steps), text=f"Guided demo · step {cur + 1} of {len(steps)}")
            c1, c2 = st.columns([5, 2])
            c1.markdown(f"**Next: {title}**  \n<span class='cso-strip'>{why}</span>", unsafe_allow_html=True)
            c2.button(label, key=f"tg_{cur}", type="primary", on_click=action, width="stretch", disabled=(cur > 0 and rec is None))
        st.button("Leave the guided demo", on_click=_exit_guided, key="tg_exit")


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


def _rec_card(db, rec, m):
    content = json.loads(rec["content_current"])
    original = json.loads(rec["content_original"])
    courses = json.loads(rec["courses"])
    evidence = json.loads(rec["evidence"])
    comp = json.loads(rec["completeness"] or "{}")
    with st.container(border=True):
        top = st.columns([3, 2])
        top[0].markdown(f"{style.badge(rec['status'])} &nbsp; <span class='cso-pill'>{ACTION_LABEL.get(rec['action_type'], rec['action_type'])}</span> "
                        f"<span class='cso-pill'>{'Live AI' if rec['generation_mode'] == 'live' else 'Demo mode' if rec['generation_mode'] == 'demo' else 'Seeded'}</span>", unsafe_allow_html=True)
        top[1].caption(f"Generated {when(rec['created_at'])} · {rec['agent_version']} · {rec['id']}")
        if rec["needs_refresh"]:
            st.warning("The meeting date changed after this was generated. Click “Prepare meeting brief” to refresh it.")
        st.caption("Review required. Nothing is shared with the customer, no one is enrolled and nothing is purchased by accepting this.")
        st.markdown(f"#### {rec['title']}")
        st.markdown(f"**Why it matters now.** {rec['why_now']}")
        st.markdown(f"**Customer goal it supports.** {rec['goal'] or 'Not recorded'}")
        st.markdown("**Suggested talking point**")
        st.markdown(f"> {rec['talking_point']}")
        if courses:
            st.markdown("**Suggested training**")
            for c in courses:
                pre = ", ".join(c["prerequisites"]) or "None"
                st.markdown(f"- **{c['title']}** ({c['course_id']}) · {'Paid' if c['paid'] else 'Free'} · {c['format']}, {c['duration_min']} minutes · prerequisites: {pre} · "
                            f"{c['learners_ready']} learner(s) ready" + (f", {c['learners_blocked']} need a prerequisite first" if c["learners_blocked"] else "") + f" · availability: {c['availability']}")
                if c.get("free_alternatives_considered"):
                    st.caption(f"Free alternatives considered: {c['free_alternatives_considered']}")
        lg = json.loads(rec["learner_group"] or "{}").get("summary")
        if lg:
            st.markdown(f"**Learner group.** {lg}")
        unk = json.loads(rec["unknowns"] or "[]")
        if unk:
            st.markdown("**Confirm with the customer**\n" + "\n".join(f"- {u}" for u in unk))
        with st.expander("Meeting brief", expanded=True):
            st.write(rec["brief"])
        with st.expander(f"Supporting evidence ({len(evidence)})"):
            if evidence:
                st.dataframe(pd.DataFrame([{"Evidence": e["label"], "Source": e["source"].replace("_", " ").capitalize(), "As of": when(e["ts"])} for e in evidence]), hide_index=True, width="stretch")
            if comp:
                st.markdown(f"**Evidence completeness:** {len(comp.get('have', []))} of {len(comp.get('have', [])) + len(comp.get('missing', []))} sources available."
                            + (f" Missing: {', '.join(comp['missing'])}." if comp.get("missing") else ""))
        if rec["status"] in ("edited",) or content != original:
            with st.expander("What changed in the review (original vs current)"):
                a, b = st.columns(2)
                a.markdown("**Original**"); a.write(original["talking_point"]); a.caption(original["title"])
                b.markdown("**Current**"); b.write(content["talking_point"]); b.caption(content["title"])
        hist = db.q("SELECT * FROM rec_feedback WHERE rec_id=? ORDER BY id", (rec["id"],))
        if hist:
            with st.expander(f"Review history ({len(hist)})"):
                st.dataframe(pd.DataFrame([{"When": when(h["ts"]), "Reviewer": h["reviewer"], "Action": status(h["action"]), "Reason": h["reason"] or "", "Note": h["note"] or ""} for h in hist]), hide_index=True, width="stretch")
        _actions(db, rec)
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
    st.title("Account Team Assistant")
    st.caption("For Account Executives and Solutions Architects preparing for a customer conversation. The assistant combines the customer's goal, product usage, "
               "learning progress and training options into a brief. Every recommendation needs a human review.")
    st.session_state.setdefault("reviewer", "Riley Chen")
    st.session_state["w_reviewer"] = st.session_state["reviewer"]
    st.selectbox("Reviewing as (synthetic identity)", REVIEWERS, key="w_reviewer", on_change=_on_reviewer)
    if st.session_state.get("guided") == "team":
        _guided(db)
    session.show_flash()

    meetings = db.q("SELECT m.*, a.name, a.lifecycle FROM meetings m JOIN accounts a ON a.id=m.account_id WHERE m.starts_at>=? AND m.starts_at<=? ORDER BY m.starts_at",
                    (team.to_iso(db.now() - team.timedelta(days=1)), team.to_iso(db.now() + team.timedelta(days=14))))
    st.markdown("### Upcoming meetings")
    c1, c2 = st.columns([4, 2])
    c1.caption("Simulated calendar for the next 14 days (no real calendar or CRM connection).")
    c2.button("Scan upcoming meetings", on_click=_scan, args=(db,), width="stretch", disabled=session.mode() == "live",
              help="Prepares briefs for every scheduled meeting in the next 7 days, using prepared rules. Disabled with an AI model so one click cannot trigger many paid calls." if session.mode() == "live"
              else "Prepares briefs for every scheduled meeting in the next 7 days. Nothing runs in the background; this is an explicit action.")
    if not meetings:
        st.info("No meetings in the next 14 days.")
        return
    recs = {m["id"]: team.latest_rec(db, m["id"]) for m in meetings}
    st.dataframe(pd.DataFrame([{"Date": when(m["starts_at"]), "Customer": m["name"], "Owner": m["owner"], "Solutions architect": m["solutions_architect"], "Stage": (m["lifecycle"] or "").capitalize(),
                                "Purpose": m["purpose"], "Meeting": status(m["status"]), "Recommendation": status(recs[m["id"]]["status"]) if recs[m["id"]] else "Not prepared"} for m in meetings]),
                 hide_index=True, width="stretch", height=min(380, 40 + 36 * len(meetings)))
    if st.session_state.get("team_scan"):
        with st.expander("Last scan result"):
            st.dataframe(pd.DataFrame(st.session_state["team_scan"]).drop(columns=["meeting_id"]).assign(Date=lambda d: d["Date"].map(when)), hide_index=True, width="stretch")

    ids = [m["id"] for m in meetings]
    sel = st.session_state.get("meeting")
    if sel not in ids:
        sel = ids[0]
        st.session_state["meeting"] = sel
    st.session_state["w_meeting"] = sel
    names = {m["id"]: f"{when(m['starts_at'], False)} · {m['name']} · {m['purpose'][:60]}" for m in meetings}
    st.selectbox("Meeting", ids, format_func=names.get, key="w_meeting", on_change=_on_meeting)
    m = next(x for x in meetings if x["id"] == sel)
    session.select(m["account_id"])
    roles = ", ".join(json.loads(m["attendee_roles"]))

    st.markdown(f"## {m['name']}")
    st.markdown(f"{style.badge(m['status'])} &nbsp; <span class='cso-pill'>{(m['lifecycle'] or '').capitalize()} stage</span> <span class='cso-pill'>Owner: {m['owner']}</span> "
                f"<span class='cso-pill'>Solutions architect: {m['solutions_architect']}</span>", unsafe_allow_html=True)
    acc = db.one("SELECT goal FROM accounts WHERE id=?", (m["account_id"],))
    st.markdown(f"**Meeting:** {when(m['starts_at'])} · {m['purpose']}  \n**Attendees:** {roles}  \n**Customer goal:** {acc['goal'] or 'Not recorded'}")
    if m["previous_start"]:
        st.caption(f"Moved from {when(m['previous_start'])}.")
    _signals(db, m["account_id"])

    if m["status"] != "scheduled":
        st.warning("This meeting is cancelled. Pending recommendations were withdrawn and no new meeting-specific prompts are created.")
    st.button("Prepare meeting brief", type="primary", on_click=_prepare, args=(db, sel), disabled=m["status"] != "scheduled",
              help="The assistant gathers evidence with its tools and saves a recommendation for your review. Nothing is sent to the customer.")
    rec = recs.get(sel)
    if rec:
        _rec_card(db, rec, m)
    else:
        st.info("No brief yet. Click “Prepare meeting brief”.")

    with st.expander("Try other situations (changes Northstar Retail's synthetic data)"):
        st.caption("Each choice reshapes Northstar's data, then you click “Prepare meeting brief” to see the assistant respond. Resetting the demo restores the original.")
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
