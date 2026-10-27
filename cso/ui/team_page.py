from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd
import streamlit as st

from .. import flags, session, team
from ..db import to_iso
from ..format import rec_status, status, when
from ..retrieval import get_retriever
from ..tools import DISMISS_REASONS, REVIEWERS
from . import style

ACTION_LABEL = {"training": "Learning recommendation", "technical_followup": "Technical follow-up first", "timing": "Timing: wait", "clarify": "Ask a clarifying question",
                "discovery": "Discovery conversation", "no_action": "No action"}
VIEWING_AS = "Sales or Customer Success"


# ------------------------------------------------------------- callbacks ---
def _ra(*a, **k):
    """Results from this page are shown only on this page."""
    session.record_action(*a, scope=("team",), **k)


def _on_meeting():
    mid = st.session_state.get("w_meeting")
    db = session.get_db()
    m = db.one("SELECT account_id FROM meetings WHERE id=?", (mid,))
    if m:
        session.select(m["account_id"], session.default_product(db, m["account_id"]))   # an explicit choice of meeting selects its customer
    st.session_state["meeting"] = mid
    if mid and team.latest_rec(db, mid):
        team.view_brief(db, mid, st.session_state["reviewer"])


def _on_reviewer():
    st.session_state["reviewer"] = st.session_state["w_reviewer"]


def _prepare(db, mid):
    try:
        res = team.prepare_meeting_brief(db, mid, session.mode(), session.llm_settings())
        if res["outcome"] == "completed" and team.latest_rec(db, mid):
            team.view_brief(db, mid, st.session_state["reviewer"])
        session.report_run(res)
    except Exception as e:
        _ra(f"Something went wrong: {type(e).__name__}: {e}", tone="error")


def _scan(db):
    rows = team.scan_upcoming(db, 7)
    st.session_state["team_scan"] = rows
    new = sum(r["New recommendation"] == "Yes" for r in rows)
    _ra(f"Checked {len(rows)} upcoming conversation(s) and prepared {new} new brief(s). Nothing was sent to any customer.",
        why="Scanning only runs when you click. Running it again creates no duplicates.")


def _act(db, rec_id, action, reason=None, note=None, revised=None, defer_days=None):
    until = None
    if defer_days:
        until = to_iso(db.now() + timedelta(days=int(defer_days)))
    res = team.review(db, rec_id, action, st.session_state["reviewer"], reason, note, revised, until)
    if res["ok"]:
        short = {"reviewed": "Marked as reviewed.",
                 "accepted": "The recommendation was accepted as a suitable next step. Nothing was sent, purchased, or enrolled.",
                 "edited": "Your edit was saved. The original wording is kept. Accept the recommendation when you are happy with it.",
                 "discussed": "Marked as discussed with the customer. This does not mean they completed training.",
                 "dismissed": "The recommendation was dismissed and will not be suggested again for this conversation.",
                 "deferred": "The recommendation was deferred. It stays saved."}[action]
        _ra(short, why=f"Recorded as {st.session_state['reviewer']}'s decision, with the time and any reason, in the review history. It also feeds the feedback summary and the evaluation page.",
            detail=f"Recommendation {rec_id} is now {action}.")
    else:
        _ra(res["error"]["message"], tone="warning")


def _edit(db, rec_id):
    revised = {"title": st.session_state[f"ed_title_{rec_id}"], "talking_point": st.session_state[f"ed_talk_{rec_id}"], "why_now": st.session_state[f"ed_why_{rec_id}"]}
    _act(db, rec_id, "edited", note=st.session_state.get(f"ed_note_{rec_id}") or None, revised=revised)


def _dismiss(db, rec_id):
    _act(db, rec_id, "dismissed", st.session_state.get(f"dr_{rec_id}"), st.session_state.get(f"dn_{rec_id}") or None)


def _defer(db, rec_id):
    _act(db, rec_id, "deferred", st.session_state.get(f"fr_{rec_id}"), None, None, st.session_state.get(f"fd_{rec_id}", 14))


def _learning(db, rec_id, stage):
    n = team.simulate_learning(db, rec_id, stage, 2)
    _ra(f"Sample update: {n} learner(s) {stage}. This is simulated customer progress, tracked separately from the recommendation." if n else "No learners could be updated for this step.",
        why="This button only creates sample learning records. It is not triggered by accepting or discussing the recommendation." if n else "", tone="success" if n else "info")


def _scenario(db):
    label = team.apply_scenario(db, st.session_state["scn"])
    session.select("ACC-041", "docs", meeting=team.NS_MEETING)
    _ra(f"Situation applied: {label}.", why="Prepare the customer brief again to see how the assistant responds to this situation.", tone="info")


# ----------------------------------------------------------------- pieces ---
STATUS_NOTE = {
    "generated": "Review required. Nothing has been shared with the customer, nobody is enrolled and nothing is purchased by accepting it.",
    "reviewed": "Reviewed. Decide whether to accept, edit, dismiss or defer it. Nothing has been shared with the customer.",
    "edited": "Edited and waiting to be accepted. Nothing has been shared with the customer.",
    "accepted": "Accepted as a suitable next step. It has not been sent to the customer and nobody has been enrolled. Mark it discussed after you raise it.",
    "discussed": "Discussed. This records that you raised it with the customer. It does not mean they completed training.",
    "deferred": "Deferred. It is saved and will not be suggested again unless you revisit it.",
    "dismissed": "Dismissed. The assistant will not suggest the same thing again for this conversation.",
    "withdrawn": "Withdrawn because the conversation was cancelled or moved. Prepare a new brief if needed.",
}


def _course_card(db, c: dict, goal: str):
    titles = {ch.doc_id: ch.title for ch in get_retriever().chunks}
    ctitle = {r["id"]: r["title"] for r in db.q("SELECT id, title FROM courses")}
    goal = goal.rstrip(". ")
    pre = ", ".join(ctitle.get(p, p) for p in c["prerequisites"]) or "None"
    skills = ", ".join(c.get("skills") or []) or c["title"]
    with st.container(border=True):
        st.markdown(f"**{c['title']}**")
        st.markdown(f"- **What it teaches:** {skills}\n"
                    f"- **Why it fits:** their goal is to {goal[:1].lower() + goal[1:]}. This course covers {skills}.\n"
                    f"- **Suitable for:** {c.get('persona') or 'Not specified'} ({c.get('difficulty') or 'level not specified'})\n"
                    f"- **Prerequisites:** {pre}" + (f" ({c['learners_ready']} learner(s) ready" + (f", {c['learners_blocked']} need a prerequisite first" if c["learners_blocked"] else "") + ")" if "learners_ready" in c else "") + "\n"
                    f"- **Duration:** {c['duration_min']} minutes ({c['format']})\n"
                    f"- **Cost:** {'Paid' if c['paid'] else 'Free'} · availability: {c['availability']}\n"
                    f"- **Source:** {titles.get(c['source_doc'], c['source_doc'])} — {c['source_section']}")
        if c.get("free_alternatives_considered"):
            st.caption(f"Free alternatives considered: {c['free_alternatives_considered']}")


def _stages(db, rec):
    got = {r["stage"]: r["n"] for r in db.q("SELECT stage, SUM(learner_count) n FROM learning_outcomes WHERE rec_id=? GROUP BY stage", (rec["id"],))}
    fb = {r["action"] for r in db.q("SELECT action FROM rec_feedback WHERE rec_id=?", (rec["id"],))}
    has_courses = bool(json.loads(rec["courses"]))
    st.markdown("**What has happened so far (four separate steps)**")
    st.dataframe(pd.DataFrame([
        {"Step": "1. A reviewer accepted the recommendation", "Status": "Yes" if "accepted" in fb else "Not yet"},
        {"Step": "2. It was discussed with the customer", "Status": "Yes" if "discussed" in fb else "Not yet"},
        {"Step": "3. The customer completed training", "Status": (f"Enrolled {got.get('enrolled', 0)} · started {got.get('started', 0)} · completed {got.get('completed', 0)} (sample, simulated)"
                                                               if got else "Not recorded") if has_courses else "Not applicable (no course recommended)"},
        {"Step": "4. Relevant product usage changed afterward", "Status": "Not measured in this demo"},
    ]), hide_index=True, width="stretch")
    st.caption("Each step is recorded separately; one never moves the next. In a real deployment, step 4 would compare activity in the relevant workflow before and after, "
               "against a comparable group of customers who did not get the recommendation. A before-and-after change alone would not show that training caused it.")
    if has_courses and rec["status"] in ("accepted", "edited", "discussed"):
        with st.expander("Simulate customer learning progress (sample data)"):
            st.caption("These buttons only create sample learning records to show how outcomes would be tracked separately. They are not triggered by accepting or discussing the recommendation, and they do not show that training changed usage.")
            c = st.columns(3)
            for col, stage in zip(c, ("enrolled", "started", "completed")):
                col.button(f"Simulate: 2 learners {stage}", key=f"lo_{rec['id']}_{stage}", on_click=_learning, args=(db, rec["id"], stage), width="stretch")


def _actions(db, rec):
    rid, st_ = rec["id"], rec["status"]
    if st_ in ("discussed", "withdrawn"):
        return
    if st_ == "dismissed":
        fb = db.one("SELECT reason FROM rec_feedback WHERE rec_id=? AND action='dismissed' ORDER BY id DESC LIMIT 1", (rid,))
        st.info(f"Dismissed ({(fb or {}).get('reason') or 'no reason recorded'}). The assistant will not recommend it again for this conversation.")
        return
    st.markdown("**Review**")
    cols = st.columns(3)
    if st_ == "generated":
        cols[0].button("Mark reviewed", key=f"rv_{rid}", on_click=_act, args=(db, rid, "reviewed"), width="stretch")
        cols[0].caption("Record that you checked the recommendation.")
    if st_ in ("generated", "reviewed", "deferred", "edited"):
        cols[1].button("Accept recommendation", key=f"ac_{rid}", type="primary", on_click=_act, args=(db, rid, "accepted"), width="stretch")
        cols[1].caption("Save it as a suitable next step. Nothing is sent, purchased, or enrolled.")
    if st_ in ("accepted", "edited"):
        cols[2].button("Mark discussed", key=f"di_{rid}", type="primary", on_click=_act, args=(db, rid, "discussed"), width="stretch")
        cols[2].caption("Record that you discussed it with the customer. This does not mean they completed training.")
    with st.expander("Edit"):
        st.caption("Change the wording or recommendation before accepting. The original is kept.")
        cur = json.loads(rec["content_current"])
        st.text_input("Recommended next step", cur["title"], key=f"ed_title_{rid}")
        st.text_area("Why it fits", cur["why_now"], key=f"ed_why_{rid}", height=90)
        st.text_area("Suggested talking point", cur["talking_point"], key=f"ed_talk_{rid}", height=110)
        st.text_input("What did you change and why? (optional)", key=f"ed_note_{rid}")
        st.button("Save edit", key=f"ed_{rid}", on_click=_edit, args=(db, rid))
    if st_ in ("generated", "reviewed", "accepted", "edited", "deferred"):
        with st.expander("Dismiss"):
            st.caption("Record why this recommendation is not suitable.")
            st.selectbox("Reason (required)", DISMISS_REASONS, key=f"dr_{rid}")
            st.text_input("Note (optional)", key=f"dn_{rid}")
            st.button("Dismiss recommendation", key=f"dm_{rid}", on_click=_dismiss, args=(db, rid))
    if st_ in ("generated", "reviewed"):
        with st.expander("Defer"):
            st.caption("Not now. Record why and when to look at it again.")
            st.selectbox("Reason (required)", DISMISS_REASONS, key=f"fr_{rid}")
            st.selectbox("Revisit in (days)", [7, 14, 30], index=1, key=f"fd_{rid}")
            st.button("Defer recommendation", key=f"df_{rid}", on_click=_defer, args=(db, rid))


def _rec_card(db, rec):
    content = json.loads(rec["content_current"])
    original = json.loads(rec["content_original"])
    courses = json.loads(rec["courses"])
    evidence = json.loads(rec["evidence"])
    comp = json.loads(rec["completeness"] or "{}")
    lg = json.loads(rec["learner_group"] or "{}")
    unk = json.loads(rec["unknowns"] or "[]")
    goal = rec["goal"] or "Not recorded"
    with st.container(border=True):
        top = st.columns([3, 2])
        top[0].markdown(f"{style.badge(rec['status'], rec_status(rec))} &nbsp; <span class='cso-pill'>{ACTION_LABEL.get(rec['action_type'], rec['action_type'])}</span>", unsafe_allow_html=True)
        top[1].caption(f"Prepared {when(rec['created_at'])} · demo mode")
        st.caption(STATUS_NOTE.get(rec["status"], ""))
        if rec["needs_refresh"]:
            st.warning("The conversation date changed after this was prepared. Choose “Prepare customer brief” again to refresh it.")
        st.markdown(f"**1. Customer goal.** {goal}")
        noticed = lg.get("noticed") or []
        st.markdown("**2. What we noticed**\n" + ("\n".join(f"- {x}" for x in noticed) if noticed else f"- {rec['why_now']}"))
        st.markdown("**3. What to confirm**\n" + ("\n".join(f"- {x}" for x in unk) if unk else "- Nothing specific. Ask what the customer needs next."))
        st.markdown(f"**4. Recommended next step.** {rec['title']}")
        st.markdown(f"Why this fits: {rec['why_now']}")
        st.markdown("**5. Suggested talking point**")
        st.markdown(f"> {rec['talking_point']}")
        if courses:
            st.markdown("**Training to discuss**")
            for c in courses:
                _course_card(db, c, goal)
        _actions(db, rec)
        with st.expander(f"Supporting evidence ({len(evidence)})"):
            if evidence:
                st.dataframe(pd.DataFrame([{"Evidence": e["label"], "Source": e["source"].replace("_", " ").capitalize(), "As of": when(e["ts"])} for e in evidence]), hide_index=True, width="stretch")
            if comp:
                st.markdown(f"**Evidence completeness:** {len(comp.get('have', []))} of {len(comp.get('have', [])) + len(comp.get('missing', []))} sources available."
                            + (f" Missing: {', '.join(comp['missing'])}." if comp.get("missing") else ""))
            st.markdown("**Internal brief**")
            st.write(rec["brief"])
        alts = lg.get("alternatives") or []
        if alts:
            with st.expander("Other training options considered"):
                for a in alts:
                    st.markdown(f"- **{a['title']}** ({'paid' if a['paid'] else 'free'}): {a['reason']}")
                st.caption("A paid option is never recommended just because usage is low.")
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
        with st.expander("Decisions and outcomes", expanded=rec["status"] in ("accepted", "edited", "discussed")):
            _stages(db, rec)


def _all_meetings(db, meetings, guided_none=False):
    recs = {m["id"]: team.latest_rec(db, m["id"]) for m in meetings}
    table = pd.DataFrame([{"Date": when(m["starts_at"]), "Customer": m["name"], "Purpose": m["purpose"], "Meeting": status(m["status"]),
                           "Brief": status(recs[m["id"]]["status"]) if recs[m["id"]] else "Not prepared"} for m in meetings])
    cfg = {"Purpose": st.column_config.TextColumn(width="large"), "Customer": st.column_config.TextColumn(width="medium"), "Date": st.column_config.TextColumn(width="medium")}
    c1, c2 = st.columns([4, 2])
    c1.caption("Sample calendar for the next 14 days. Choose one to open that customer's brief.")
    c2.button("Prepare briefs for all", on_click=_scan, args=(db,), width="stretch", help="Prepares a brief for every scheduled conversation in the next 7 days. Nothing runs in the background; this is an explicit action.")
    st.dataframe(table, hide_index=True, width="stretch", height=min(380, 40 + 36 * len(meetings)), column_config=cfg)
    if st.session_state.get("team_scan"):
        st.markdown("**Last run**")
        st.dataframe(pd.DataFrame(st.session_state["team_scan"]).drop(columns=["meeting_id"]).assign(Date=lambda d: d["Date"].map(when)), hide_index=True, width="stretch")
    st.session_state["w_meeting_all"] = st.session_state.get("meeting")
    ids = [m["id"] for m in meetings]
    names = {m["id"]: f"{when(m['starts_at'], False)} · {m['name']} · {m['purpose'][:60]}" for m in meetings}
    if st.session_state["w_meeting_all"] not in ids:
        st.session_state["w_meeting_all"] = None
    st.selectbox("Open a conversation", ids, index=None, format_func=names.get, key="w_meeting_all", placeholder="Choose a conversation…", on_change=_on_all)


def _on_all():
    st.session_state["w_meeting"] = st.session_state.get("w_meeting_all")
    _on_meeting()


# ------------------------------------------------------------------- page ---
def render():
    db = session.get_db()
    st.title("Meeting preparation")
    st.caption("Prepare a customer brief with relevant insights, suggested next steps, and talking points.")
    st.session_state.setdefault("reviewer", "Riley Chen")
    st.session_state["w_reviewer"] = st.session_state["reviewer"]
    aid, _ = style.account_picker(db, with_product=False)
    with st.expander("Reviewer name (sample)"):
        st.selectbox("Reviewer", REVIEWERS, key="w_reviewer", on_change=_on_reviewer)
    session.show_flash()
    session.show_action("team")
    meetings = db.q("SELECT m.*, a.name, a.lifecycle FROM meetings m JOIN accounts a ON a.id=m.account_id WHERE m.starts_at>=? AND m.starts_at<=? ORDER BY m.starts_at",
                    (to_iso(db.now() - timedelta(days=1)), to_iso(db.now() + timedelta(days=14))))
    if not aid:
        st.info("**Start here:** choose a customer above, or pick one on the Overview. Northstar Retail shows a potential learning need.")
        with st.expander("All upcoming conversations (sample calendar)"):
            _all_meetings(db, meetings)
        return
    name = db.one("SELECT name FROM accounts WHERE id=?", (aid,))["name"]
    mine = [m for m in meetings if m["account_id"] == aid]
    if not mine:
        style.context_line(db, aid, viewing_as=VIEWING_AS)
        st.info(f"No conversation with {name} is scheduled in the sample calendar, so there is no brief to prepare. Choose another customer, or see all upcoming conversations below.")
        with st.expander("All upcoming conversations (sample calendar)"):
            _all_meetings(db, meetings)
        return
    ids = [m["id"] for m in mine]
    sel = st.session_state.get("meeting")
    if sel not in ids:
        sel = ids[0]
        st.session_state["meeting"] = sel
    if len(mine) > 1:
        st.session_state["w_meeting"] = sel
        st.selectbox("Conversation", ids, format_func=lambda i: f"{when(next(m['starts_at'] for m in mine if m['id'] == i))} · {next(m['purpose'] for m in mine if m['id'] == i)[:60]}", key="w_meeting", on_change=_on_meeting)
    m = next(x for x in mine if x["id"] == sel)
    style.context_line(db, aid, viewing_as=VIEWING_AS)
    st.markdown(f"<span class='cso-pill'>{(m['lifecycle'] or '').capitalize()} stage</span> <span class='cso-pill'>Owner: {m['owner']}</span>", unsafe_allow_html=True)
    roles = ", ".join(json.loads(m["attendee_roles"]))
    st.markdown(f"**Conversation:** {when(m['starts_at'])} · {m['purpose']}  \n**Attendees:** {roles}")
    if m["previous_start"]:
        st.caption(f"Moved from {when(m['previous_start'])}.")
    if m["status"] != "scheduled":
        st.warning("This conversation is cancelled. Pending recommendations were withdrawn and no new prompts are created for it.")
    rec = team.latest_rec(db, sel)
    if rec is None:
        st.markdown("**Prepare customer brief**")
    st.button("Prepare customer brief" if rec is None else "Refresh the customer brief", type="primary" if rec is None else "secondary", on_click=_prepare, args=(db, sel),
              disabled=m["status"] != "scheduled", key="prep_main",
              help="The assistant gathers evidence with its tools and saves a recommendation for your review. Nothing is sent to the customer."
              if m["status"] == "scheduled" else "The conversation is cancelled, so no brief can be prepared.")
    st.caption("Review this customer's usage, learning progress, and suggested talking points before your conversation.")
    if rec:
        _rec_card(db, rec)
    else:
        st.info("No brief yet. Choose “Prepare customer brief”.")

    with st.popover("Reset this customer's demo activity"):
        st.markdown(f"This undoes what you did with **{name}** in this session: briefs, review decisions and sample learning records. Other customers are not changed.")
        st.button(f"Yes, reset {name}", key="reset_cust_team", on_click=session.reset_customer, args=(aid,), type="primary")
    with st.expander("All upcoming conversations (sample calendar)"):
        _all_meetings(db, meetings)
    if flags.advanced():
        with st.expander("Reviewer option: try other situations (changes Northstar Retail's sample data)"):
            st.caption("Each choice reshapes Northstar's data, then you prepare the customer brief again to see the assistant respond.")
            st.selectbox("Situation", list(team.SCENARIOS), format_func=team.SCENARIOS.get, key="scn")
            st.button("Apply situation", on_click=_scenario, args=(db,))
    with st.expander("Feedback summary (what reviewers are telling the product team)"):
        fs = team.feedback_summary(db)
        st.caption("Includes sample history. Use it to decide what to build or fix; the assistant does not learn from it automatically.")
        a, b = st.columns(2)
        a.markdown("**Dismissal and deferral reasons**")
        a.dataframe(pd.DataFrame(fs["reasons"]).rename(columns={"reason": "Reason", "n": "Count"}) if fs["reasons"] else pd.DataFrame({"Reason": []}), hide_index=True, width="stretch")
        b.markdown("**Recommendations that were edited**")
        b.dataframe(pd.DataFrame(fs["edited"]).rename(columns={"action_type": "Type", "title": "Recommendation", "n": "Edits"}) if fs["edited"] else pd.DataFrame({"Recommendation": []}), hide_index=True, width="stretch")
        st.markdown(f"**Accepted but not yet discussed:** {len(fs['accepted_not_discussed'])}")
        st.markdown("**Repeated information gaps:** " + ("; ".join(f"{g['gap']} ({g['n']})" for g in fs["gaps"]) if fs["gaps"] else "none yet"))
