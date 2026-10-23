"""Synthetic Account Team data: course catalog, Northstar Retail, prospects, meetings and recommendation history."""
from __future__ import annotations

import json
from datetime import timedelta

from .db import DB, to_iso

NORTHSTAR = "ACC-041"
OWNERS = ["Riley Chen", "Jamie Ortiz", "Sasha Imani"]
SAS = ["Morgan Ellis", "Devon Park"]

COURSES = [
    # id, product, topic, title, persona, difficulty, prereqs, skills, format, minutes, paid, price_note, availability, source_doc, source_section
    ("CRS-101", "docs", "Fundamentals", "Docs Fundamentals", "everyone", "beginner", [], ["create pages", "publish pages", "basic sharing"],
     "self-paced video", 45, 0, "Free", "always", "DOC-111", "Docs Fundamentals"),
    ("CRS-102", "docs", "Shared documentation workflows", "Shared Documentation Workflows", "team leads and contributors", "intermediate", ["CRS-101"],
     ["page templates", "review and approval flow", "shared spaces", "sharing with groups"], "self-paced module", 90, 0, "Free", "always", "DOC-111", "Shared Documentation Workflows"),
    ("CRS-103", "docs", "Administration", "Docs Administration and Directory Setup", "workspace administrators", "intermediate", ["CRS-101"],
     ["connect a directory", "groups and permissions"], "self-paced module", 60, 0, "Free", "always", "DOC-111", "Docs Administration and Directory Setup"),
    ("CRS-104", "docs", "Rollout planning", "Rolling Out Shared Documentation Across Teams", "program leads and larger teams", "advanced", ["CRS-102"],
     ["rollout planning", "ownership and review cadence"], "live workshop", 180, 1, "Paid workshop", "monthly live session", "DOC-111", "Rolling Out Shared Documentation Across Teams"),
    ("CRS-201", "tasks", "Fundamentals", "Tasks Fundamentals", "everyone", "beginner", [], ["workspaces", "projects", "tasks"], "self-paced video", 40, 0, "Free", "always", "DOC-113", "Tasks Fundamentals"),
    ("CRS-202", "tasks", "Planning", "Tasks: Planning with Projects", "project leads", "intermediate", ["CRS-201"], ["planning", "owners and due dates"], "self-paced module", 75, 0, "Free", "always", "DOC-113", "Tasks: Planning with Projects"),
    ("CRS-301", "support", "Setup", "Support Workspace Setup", "administrators", "beginner", [], ["service workspace", "request channels"], "self-paced video", 40, 0, "Free", "always", "DOC-113", "Support Workspace Setup"),
    ("CRS-302", "support", "Request workflows", "Support: Building Request Workflows", "service managers", "advanced", ["CRS-301"], ["queues", "routing", "resolution workflows"], "live workshop", 120, 1, "Paid workshop", "monthly live session", "DOC-113", "Support: Building Request Workflows"),
]

NS_LEARNERS = [("L-001", "Operations Manager"), ("L-002", "Merchandising Lead"), ("L-003", "Store Support Lead"), ("L-004", "Operations Analyst"),
               ("L-005", "Merchandiser"), ("L-006", "Support Agent Lead"), ("L-007", "Program Coordinator"), ("L-008", "Finance Partner")]


def seed_catalog(db: DB, now):
    for c in COURSES:
        db.x("INSERT INTO courses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (c[0], c[1], c[2], c[3], c[4], c[5], json.dumps(c[6]), json.dumps(c[7]), c[8], c[9], c[10], c[11], c[12], c[13], c[14], to_iso(now - timedelta(days=30))))


def _learner(db, lid, aid, role, course, status, done_days_ago, now, updated_days_ago=3):
    db.insert("learner_records", learner_id=lid, account_id=aid, role=role, course_id=course, status=status,
              completed_at=to_iso(now - timedelta(days=done_days_ago)) if status == "completed" else None,
              record_updated_at=to_iso(now - timedelta(days=updated_days_ago)))


def seed_northstar_learners(db: DB, now):
    aid = NORTHSTAR
    for i, (lid, role) in enumerate(NS_LEARNERS):
        if i < 6:
            _learner(db, lid, aid, role, "CRS-101", "completed", 40 - i * 3, now)
        elif i == 6:
            _learner(db, lid, aid, role, "CRS-101", "enrolled", 0, now)
    _learner(db, "L-001", aid, "Operations Manager", "CRS-102", "completed", 10, now)
    _learner(db, "L-002", aid, "Merchandising Lead", "CRS-102", "completed", 8, now)
    _learner(db, "L-003", aid, "Store Support Lead", "CRS-102", "started", 0, now)


def seed_northstar(db: DB, rng, now):
    aid = NORTHSTAR
    db.next_id("ACC")
    db.insert("accounts", id=aid, name="Northstar Retail", segment="Mid-market", scenario="northstar", needs_directory=0,
              goal="Introduce a shared documentation workflow across the Operations, Merchandising and Store Support teams.",
              data_refreshed_at=to_iso(now - timedelta(hours=2)), lifecycle="adoption", owner="Riley Chen", solutions_architect="Morgan Ellis")
    db.insert("contacts", id=db.next_id("CON"), account_id=aid, name="Taylor Brooks", email="taylor@northstarretail.example", role="Workspace administrator",
              is_admin=1, opted_out=0, preferred_channel="email", consent=1)
    db.insert("subscriptions", id=db.next_id("SUB"), account_id=aid, product="docs", bundle=0, status="active")
    start = now - timedelta(days=75)
    db.insert("rollout_plans", account_id=aid, product="docs", planned_start=to_iso(start))
    for key, d in (("workspace_created", 73), ("first_doc_published", 66), ("first_doc_shared", 58)):
        db.insert("product_events", account_id=aid, product="docs", event_type=key, ts=to_iso(now - timedelta(days=d)))
    # adoption signal: the shared workflow was used actively, then faded
    for d in (52, 49, 46, 43, 41, 38, 35, 33, 30, 26, 21, 15):
        db.insert("product_events", account_id=aid, product="docs", event_type="shared_workflow_used", ts=to_iso(now - timedelta(days=d)))
    for d in (60, 52, 45, 39, 31, 24, 17, 9, 4):
        db.insert("product_events", account_id=aid, product="docs", event_type="usage_session", ts=to_iso(now - timedelta(days=d)))
    j = db.next_id("JRN")
    db.insert("journeys", id=j, account_id=aid, product="docs", state="completed", paused_until=None, attempted_docs="[]", started_at=to_iso(start),
              updated_at=to_iso(now - timedelta(days=58)), completed_at=to_iso(now - timedelta(days=58)))
    seed_northstar_learners(db, now)
    db.insert("meetings", id="MTG-001", account_id=aid, owner="Riley Chen", solutions_architect="Morgan Ellis",
              starts_at=to_iso((now + timedelta(days=1)).replace(hour=10)), purpose="Quarterly adoption review: expanding the shared documentation workflow",
              attendee_roles=json.dumps(["VP Operations", "Program Coordinator", "Merchandising Lead"]), status="scheduled")
    db.next_id("MTG")


def seed_team_history(db: DB, rng, now):
    """Prospects, upcoming meetings on other accounts, and past recommendation history. All synthetic."""
    for n, (name, goal) in enumerate((("Alder Wholesale", "Evaluate a shared documentation tool for the operations team."),
                                      ("Fernhill Clinics", "Evaluate request tracking for the IT help desk.")), start=42):
        aid = f"ACC-{n:03d}"
        db.insert("accounts", id=aid, name=name, segment="SMB", goal=goal, scenario="prospect", needs_directory=0,
                  data_refreshed_at=to_iso(now - timedelta(hours=5)), lifecycle="prospect", owner=rng.choice(OWNERS), solutions_architect=rng.choice(SAS))
        db.insert("contacts", id=db.next_id("CON"), account_id=aid, name="Casey Morgan", email=f"casey@{name.split()[0].lower()}.example", role="Evaluation lead",
                  is_admin=1, opted_out=0, preferred_channel="email", consent=1)
    mids = iter(range(2, 100))

    def meet(aid, days, purpose, roles, status="scheduled"):
        mid = f"MTG-{next(mids):03d}"
        a = db.one("SELECT owner, solutions_architect FROM accounts WHERE id=?", (aid,))
        owner = a["owner"] or rng.choice(OWNERS)
        sa = a["solutions_architect"] or rng.choice(SAS)
        db.x("UPDATE accounts SET owner=?, solutions_architect=? WHERE id=?", (owner, sa, aid))
        db.insert("meetings", id=mid, account_id=aid, owner=owner, solutions_architect=sa, starts_at=to_iso((now + timedelta(days=days)).replace(hour=rng.choice([10, 11, 14, 15]), minute=0, second=0)),
                  purpose=purpose, attendee_roles=json.dumps(roles), status=status)
        return mid

    for scen, n, purposes in (("technical", 2, ["Review the open directory issue and plan next steps"]), ("plan_later", 2, ["Plan the upcoming rollout and training"]),
                              ("progressing", 2, ["Onboarding check-in and next milestones"]), ("not_started", 1, ["Kick-off to restart stalled setup"]),
                              ("completed", 1, ["Adoption review after completed setup"])):
        for a in db.q("SELECT id FROM accounts WHERE scenario=? ORDER BY id LIMIT ?", (scen, n)):
            meet(a["id"], rng.randint(2, 9), purposes[0], ["Workspace administrator", "Team lead"])
    for a in db.q("SELECT id FROM accounts WHERE scenario='prospect' ORDER BY id"):
        meet(a["id"], rng.randint(3, 8), "Evaluation call: confirm goals and success criteria", ["Evaluation lead"])

    # past meetings with a seeded recommendation history (synthetic)
    hist = [("accepted", None, "discussed"), ("dismissed", "Wrong timing", None), ("deferred", "Technical blocker", None), ("edited", None, "discussed"),
            ("dismissed", "Customer already trained", None), ("accepted", None, None)]
    rows = db.q("SELECT id FROM accounts WHERE scenario IN ('completed','progressing','technical','plan_later') ORDER BY id LIMIT 6")
    for (status, reason, final), a in zip(hist, rows):
        mid = meet(a["id"], -rng.randint(6, 40), "Adoption review", ["Team lead"], status="completed")
        rid = db.next_id("REC")
        content = {"title": "Share the learning path for the shared documentation workflow", "why_now": "Seeded example.", "talking_point": "Ask whether the team needs help applying the workflow."}
        final_status = final or status
        db.insert("recommendations", id=rid, account_id=a["id"], meeting_id=mid, status=final_status, action_type="training", title=content["title"], why_now=content["why_now"],
                  goal="", talking_point=content["talking_point"], brief="Seeded historical recommendation.", evidence="[]", learner_group="{}", courses="[]", unknowns="[]",
                  completeness="{}", generation_mode="seed", agent_version="seed", dedupe_key=f"{a['id']}|{mid}|training|seed", needs_refresh=0,
                  content_original=json.dumps(content), content_current=json.dumps(content), created_at=to_iso(now - timedelta(days=45)), updated_at=to_iso(now - timedelta(days=30)))
        db.insert("rec_feedback", rec_id=rid, account_id=a["id"], meeting_id=mid, reviewer="Riley Chen", action=status if status != "edited" else "edited", reason=reason, note=None,
                  original=json.dumps(content), revised=json.dumps({**content, "talking_point": "Edited wording."}) if status == "edited" else None, ts=to_iso(now - timedelta(days=31)))
        if final == "discussed":
            db.insert("rec_feedback", rec_id=rid, account_id=a["id"], meeting_id=mid, reviewer="Riley Chen", action="discussed", reason=None, note=None, original=None, revised=None, ts=to_iso(now - timedelta(days=29)))
        if status in ("accepted", "edited"):
            for stage, n in (("enrolled", 3), ("started", 2), ("completed", 1))[: rng.randint(1, 3)]:
                db.insert("learning_outcomes", rec_id=rid, account_id=a["id"], stage=stage, learner_count=n, ts=to_iso(now - timedelta(days=20)))
        db.insert("meeting_events", meeting_id=mid, event="brief_generated", reviewer="system", ts=to_iso(now - timedelta(days=46)))
        db.insert("meeting_events", meeting_id=mid, event="brief_viewed", reviewer="Riley Chen", ts=to_iso(now - timedelta(days=45)))
