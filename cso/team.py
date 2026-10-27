"""Meeting-preparation workflow services: meeting preparation, review, scenarios and measurement.

Like services.py, these run only from button callbacks. Rendering never calls them.
"""
from __future__ import annotations

import json
from datetime import timedelta  # noqa: F401 (re-exported for the UI)

from .agent import run_agent
from .db import DB, from_iso, to_iso
from .seed_team import NORTHSTAR, seed_northstar_learners
from .tools import ACTIVE_REC, DISMISS_REASONS, REVIEWERS, ToolContext, execute_tool

NS_MEETING = "MTG-001"
SCENARIOS = {
    "skills_gap": "Possible skills gap (free learning option)",
    "technical_blocker": "A technical blocker is open",
    "delayed_rollout": "The customer delayed the rollout",
    "course_completed": "The relevant course is already completed",
    "missing_learners": "Learner information is missing",
    "stale_learners": "Learner records are out of date",
    "unmet_prerequisite": "Prerequisites are not met",
    "small_team": "Small team: free self-paced option",
    "paid_workshop": "Larger team: a paid workshop may fit",
    "already_dismissed": "A recommendation was already dismissed",
    "meeting_changed": "The meeting date changed",
    "meeting_cancelled": "The meeting was cancelled",
}


# --------------------------------------------------------------- preparing ---
def _rev(db: DB, meeting_id: str) -> str:
    n = db.one("SELECT (SELECT COUNT(*) FROM recommendations WHERE meeting_id=?) + (SELECT COUNT(*) FROM rec_feedback WHERE meeting_id=?) n", (meeting_id, meeting_id))["n"]
    m = db.one("SELECT starts_at, status FROM meetings WHERE id=?", (meeting_id,))
    return f"{n}:{m['starts_at']}:{m['status']}"


def prepare_meeting_brief(db: DB, meeting_id: str, mode: str = "scripted", llm: dict | None = None) -> dict:
    m = db.one("SELECT * FROM meetings WHERE id=?", (meeting_id,))
    if not m:
        raise ValueError("Unknown meeting")
    ref = f"prep:{meeting_id}:{to_iso(db.now())}:{_rev(db, meeting_id)}"
    return run_agent(db, m["account_id"], None, {"type": "meeting_prep", "ref": ref, "meeting_id": meeting_id}, mode, llm)


def upcoming(db: DB, days: int = 14) -> list[dict]:
    end = to_iso(db.now() + timedelta(days=days))
    return db.q("SELECT m.*, a.name, a.lifecycle, a.goal FROM meetings m JOIN accounts a ON a.id=m.account_id WHERE m.status='scheduled' AND m.starts_at>? AND m.starts_at<=? ORDER BY m.starts_at",
                (to_iso(db.now()), end))


def scan_upcoming(db: DB, days: int = 7) -> list[dict]:
    rows = []
    for m in upcoming(db, days):
        before = db.one("SELECT COUNT(*) n FROM recommendations WHERE meeting_id=?", (m["id"],))["n"]
        r = run_agent(db, m["account_id"], None, {"type": "meeting_prep", "ref": f"scan:{m['id']}:{to_iso(db.now())}:{_rev(db, m['id'])}", "meeting_id": m["id"]}, "scripted")
        after = db.one("SELECT COUNT(*) n FROM recommendations WHERE meeting_id=?", (m["id"],))["n"]
        rows.append({"meeting_id": m["id"], "Account": m["name"], "Meeting": m["purpose"], "Date": m["starts_at"], "New recommendation": "Yes" if after > before else "No", "Result": r["summary"]})
    return rows


def view_brief(db: DB, meeting_id: str, reviewer: str):
    """Record one view per reviewer and meeting. Streamlit reruns never call this."""
    if not db.one("SELECT 1 x FROM meeting_events WHERE meeting_id=? AND event='brief_viewed' AND reviewer=?", (meeting_id, reviewer)):
        db.insert("meeting_events", meeting_id=meeting_id, event="brief_viewed", reviewer=reviewer, ts=to_iso(db.now()))


def latest_rec(db: DB, meeting_id: str) -> dict | None:
    return db.one("SELECT * FROM recommendations WHERE meeting_id=? AND status!='withdrawn' ORDER BY created_at DESC, id DESC LIMIT 1", (meeting_id,))


# ------------------------------------------------------------------ review ---
def review(db: DB, rec_id: str, action: str, reviewer: str, reason: str | None = None, note: str | None = None, revised: dict | None = None,
           defer_until: str | None = None) -> dict:
    r = db.one("SELECT * FROM recommendations WHERE id=?", (rec_id,))
    if not r:
        raise ValueError("Unknown recommendation")
    ctx = ToolContext(db, None, r["account_id"], actor="human")
    if r["status"] == "generated" and action in ("accepted", "edited", "dismissed", "deferred"):
        execute_tool(ctx, "record_recommendation_feedback", {"account_id": r["account_id"], "rec_id": rec_id, "action": "reviewed", "reviewer": reviewer})
    args = {"account_id": r["account_id"], "rec_id": rec_id, "action": action, "reviewer": reviewer, "reason": reason, "note": note, "revised": revised, "defer_until": defer_until}
    return execute_tool(ctx, "record_recommendation_feedback", {k: v for k, v in args.items() if v is not None}, f"Review action by {reviewer}")


def withdraw_recs(db: DB, meeting_id: str, reason: str) -> int:
    rows = db.q("SELECT id, account_id FROM recommendations WHERE meeting_id=? AND status IN ('generated','reviewed','accepted','edited','deferred')", (meeting_id,))
    for r in rows:
        db.update("recommendations", r["id"], status="withdrawn", updated_at=to_iso(db.now()))
        db.insert("rec_feedback", rec_id=r["id"], account_id=r["account_id"], meeting_id=meeting_id, reviewer="system", action="withdrawn", reason=reason, note=None,
                  original=None, revised=None, ts=to_iso(db.now()))
    return len(rows)


def cancel_meeting(db: DB, meeting_id: str) -> int:
    m = db.one("SELECT * FROM meetings WHERE id=?", (meeting_id,))
    db.update("meetings", meeting_id, status="cancelled")
    n = withdraw_recs(db, meeting_id, "Meeting cancelled")
    db.timeline(m["account_id"], "system", "tool_action", f"Meeting {meeting_id} cancelled; {n} pending recommendation(s) withdrawn")
    return n


def reschedule_meeting(db: DB, meeting_id: str, days: int) -> int:
    m = db.one("SELECT * FROM meetings WHERE id=?", (meeting_id,))
    new = from_iso(m["starts_at"]) + timedelta(days=days)
    db.update("meetings", meeting_id, previous_start=m["starts_at"], starts_at=to_iso(new))
    n = db.x("UPDATE recommendations SET needs_refresh=1 WHERE meeting_id=? AND status IN ('generated','reviewed','accepted','edited')", (meeting_id,)).rowcount
    db.timeline(m["account_id"], "system", "tool_action", f"Meeting {meeting_id} moved to {to_iso(new)[:10]}; {n} recommendation(s) need a refresh")
    return n


def simulate_learning(db: DB, rec_id: str, stage: str, count: int = 2) -> int:
    """Sample customer learning update. Kept separate from the reviewer's accept/dismiss decision."""
    r = db.one("SELECT * FROM recommendations WHERE id=?", (rec_id,))
    courses = json.loads(r["courses"])
    if not courses or stage not in ("enrolled", "started", "completed"):
        return 0
    cid = courses[0]["course_id"]
    learners = {x["learner_id"]: x for x in db.q("SELECT * FROM learner_records WHERE account_id=?", (r["account_id"],))}
    pool = sorted({x["learner_id"] for x in learners.values()})
    now = to_iso(db.now())
    done = 0
    for lid in pool:
        if done >= count:
            break
        rows = db.q("SELECT * FROM learner_records WHERE account_id=? AND learner_id=? AND course_id=?", (r["account_id"], lid, cid))
        rank = {"not_started": 0, "enrolled": 1, "started": 2, "completed": 3}
        cur = rows[0]["status"] if rows else "not_started"
        if rank[cur] >= rank[stage]:
            continue
        if rows:
            db.x("UPDATE learner_records SET status=?, completed_at=?, record_updated_at=? WHERE id=?", (stage, now if stage == "completed" else None, now, rows[0]["id"]))
        else:
            role = next(x["role"] for x in learners.values() if x["learner_id"] == lid)
            db.insert("learner_records", learner_id=lid, account_id=r["account_id"], role=role, course_id=cid, status=stage, completed_at=now if stage == "completed" else None, record_updated_at=now)
        done += 1
    if done:
        db.insert("learning_outcomes", rec_id=rec_id, account_id=r["account_id"], stage=stage, learner_count=done, ts=now)
        db.timeline(r["account_id"], "system", "event", f"Sample learning update: {done} learner(s) {stage} {cid}")
    return done


# --------------------------------------------------------------- scenarios ---
def restore_northstar(db: DB):
    aid, now = NORTHSTAR, db.now()
    rids = [r["id"] for r in db.q("SELECT id FROM recommendations WHERE meeting_id=?", (NS_MEETING,))]
    for rid in rids:
        db.x("DELETE FROM learning_outcomes WHERE rec_id=?", (rid,))
    for t in ("recommendations", "rec_feedback", "meeting_events"):
        db.x(f"DELETE FROM {t} WHERE meeting_id=?", (NS_MEETING,))
    db.x("DELETE FROM idempotency WHERE key LIKE ? OR key LIKE ?", (f"prep:{NS_MEETING}:%", f"scan:{NS_MEETING}:%"))
    for t in ("learner_records", "support_cases", "human_tasks"):
        db.x(f"DELETE FROM {t} WHERE account_id=?", (aid,))
    db.x("UPDATE rollout_plans SET planned_start=? WHERE account_id=? AND product='docs'", (to_iso(now - timedelta(days=75)), aid))
    db.x("UPDATE meetings SET status='scheduled', starts_at=?, previous_start=NULL WHERE id=?", (to_iso((now + timedelta(days=1)).replace(hour=10, minute=0, second=0)), NS_MEETING))
    db.x("UPDATE accounts SET data_refreshed_at=? WHERE id=?", (to_iso(now - timedelta(hours=2)), aid))
    seed_northstar_learners(db, now)


def _add_learners(db, ids, role, courses, now):
    for lid in ids:
        for c in courses:
            db.insert("learner_records", learner_id=lid, account_id=NORTHSTAR, role=role, course_id=c, status="completed",
                      completed_at=to_iso(now - timedelta(days=20)), record_updated_at=to_iso(now - timedelta(days=3)))


def apply_scenario(db: DB, key: str) -> str:
    """Reshape Northstar Retail's synthetic data. Re-running 'Prepare meeting brief' then shows how the assistant responds."""
    restore_northstar(db)
    now, aid = db.now(), NORTHSTAR
    if key == "technical_blocker":
        db.insert("support_cases", id=db.next_id("CASE"), account_id=aid, product="docs", subject="Shared space permissions fail for the Store Support group", category="configuration",
                  status="open", blocking=1, created_at=to_iso(now - timedelta(days=2)))
    elif key == "delayed_rollout":
        db.x("UPDATE rollout_plans SET planned_start=? WHERE account_id=? AND product='docs'", (to_iso(now + timedelta(days=30)), aid))
    elif key == "course_completed":
        for lid in ("L-003", "L-004", "L-005", "L-006", "L-007"):
            db.x("DELETE FROM learner_records WHERE account_id=? AND learner_id=? AND course_id='CRS-102'", (aid, lid))
        _add_learners(db, ["L-003", "L-004", "L-005", "L-006", "L-007"], "Team member", ["CRS-102"], now)
        db.x("UPDATE learner_records SET status='completed', completed_at=? WHERE account_id=? AND course_id='CRS-101'", (to_iso(now - timedelta(days=30)), aid))
    elif key == "missing_learners":
        db.x("DELETE FROM learner_records WHERE account_id=?", (aid,))
    elif key == "stale_learners":
        db.x("UPDATE learner_records SET record_updated_at=? WHERE account_id=?", (to_iso(now - timedelta(days=60)), aid))
    elif key == "unmet_prerequisite":
        db.x("UPDATE learner_records SET status='enrolled', completed_at=NULL WHERE account_id=? AND course_id='CRS-101'", (aid,))
        db.x("DELETE FROM learner_records WHERE account_id=? AND course_id='CRS-102'", (aid,))
    elif key == "small_team":
        db.x("DELETE FROM learner_records WHERE account_id=? AND learner_id NOT IN ('L-001','L-002','L-003')", (aid,))
        db.x("DELETE FROM learner_records WHERE account_id=? AND course_id='CRS-102'", (aid,))
    elif key == "paid_workshop":
        _add_learners(db, [f"L-{100 + i}" for i in range(1, 22)], "Team member", ["CRS-101", "CRS-102"], now)
    elif key in ("already_dismissed", "meeting_changed", "meeting_cancelled"):
        res = prepare_meeting_brief(db, NS_MEETING)
        rec = latest_rec(db, NS_MEETING)
        if key == "already_dismissed" and rec:
            review(db, rec["id"], "dismissed", "Riley Chen", "Wrong timing", "Dismissed in an earlier review (scenario).")
        elif key == "meeting_changed":
            reschedule_meeting(db, NS_MEETING, 2)
        elif key == "meeting_cancelled":
            cancel_meeting(db, NS_MEETING)
    return SCENARIOS[key]


# ------------------------------------------------------------- measurement ---
def _count(db, sql, params=()):
    return db.one(sql, params)["n"]


def team_metrics(db: DB, origin: str) -> dict:
    o = (origin,)
    horizon = to_iso(db.now() + timedelta(days=14))
    if origin == "session":
        eligible = _count(db, "SELECT COUNT(*) n FROM meetings WHERE status='scheduled' AND starts_at>? AND starts_at<=?", (to_iso(db.now()), horizon))
        scope = "scheduled meetings in the next 14 days"
    else:
        eligible = _count(db, "SELECT COUNT(*) n FROM meetings WHERE origin='seed' AND status='completed'")
        scope = "past seeded meetings"
    fb = lambda a: _count(db, "SELECT COUNT(DISTINCT rec_id) n FROM rec_feedback WHERE origin=? AND action=?", (origin, a))
    gen = _count(db, "SELECT COUNT(DISTINCT meeting_id) n FROM meeting_events WHERE origin=? AND event='brief_generated'", o)
    lo = lambda st: _count(db, "SELECT COALESCE(SUM(learner_count),0) n FROM learning_outcomes WHERE origin=? AND stage=?", (origin, st))
    return {"eligible": eligible, "scope": scope, "briefs_generated": gen,
            "briefs_viewed": _count(db, "SELECT COUNT(DISTINCT meeting_id) n FROM meeting_events WHERE origin=? AND event='brief_viewed'", o),
            "reviewed": _count(db, "SELECT COUNT(DISTINCT rec_id) n FROM rec_feedback WHERE origin=? AND reviewer!='system' AND action!='discussed'", o),
            "accepted": fb("accepted"), "edited": fb("edited"), "dismissed": fb("dismissed"), "deferred": fb("deferred"), "discussed": fb("discussed"),
            "recs": _count(db, "SELECT COUNT(*) n FROM recommendations WHERE origin=?", o),
            "enrolled": lo("enrolled"), "started": lo("started"), "completed": lo("completed")}


def feedback_summary(db: DB) -> dict:
    reasons = db.q("SELECT reason, COUNT(*) n FROM rec_feedback WHERE action IN ('dismissed','deferred') AND reason IS NOT NULL GROUP BY reason ORDER BY n DESC")
    edited = db.q("SELECT r.action_type, r.title, COUNT(*) n FROM rec_feedback f JOIN recommendations r ON r.id=f.rec_id WHERE f.action='edited' GROUP BY r.action_type, r.title ORDER BY n DESC")
    pending = db.q("SELECT id, account_id, meeting_id, title FROM recommendations WHERE status IN ('accepted','edited') ORDER BY created_at")
    gaps: dict[str, int] = {}
    for r in db.q("SELECT unknowns FROM recommendations WHERE unknowns IS NOT NULL AND unknowns!='[]'"):
        for u in json.loads(r["unknowns"]):
            gaps[u] = gaps.get(u, 0) + 1
    return {"reasons": reasons, "edited": edited, "accepted_not_discussed": pending,
            "gaps": sorted(({"gap": k, "n": v} for k, v in gaps.items() if v > 1), key=lambda x: -x["n"])[:5]}
