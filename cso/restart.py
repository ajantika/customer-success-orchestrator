"""Restart one walkthrough without touching the other.

A fresh seeded database is built in memory and only the rows that belong to the chosen customer are copied back,
so progress in the other workflow is kept. The demo clock returns to the original demo date, which is stated in the UI.
"""
from __future__ import annotations

from .datagen import build_db
from .db import DB, to_iso

ACCOUNT_TABLES = ["accounts", "contacts", "subscriptions", "rollout_plans", "product_events", "support_cases", "interactions", "journeys",
                  "scheduled_actions", "human_tasks", "agent_runs", "tool_executions", "guard_log", "meetings", "learner_records",
                  "recommendations", "rec_feedback", "learning_outcomes"]
WORKFLOWS = {"onboarding": ("ACC-001", "Maple Design"), "team": ("ACC-041", "Northstar Retail")}


def restart_workflow(db: DB, which: str) -> str:
    aid, name = WORKFLOWS[which]
    fresh = build_db()
    jids = [r["id"] for r in db.q("SELECT id FROM journeys WHERE account_id=?", (aid,))]
    mids = [r["id"] for r in db.q("SELECT id FROM meetings WHERE account_id=?", (aid,))]
    rids = [r["id"] for r in db.q("SELECT id FROM recommendations WHERE account_id=?", (aid,))]
    cols = lambda d, t: [c["name"] for c in d.q(f"PRAGMA table_info({t})")]
    for t in ACCOUNT_TABLES:
        db.x(f"DELETE FROM {t} WHERE account_id=?", (aid,)) if "account_id" in cols(db, t) else db.x(f"DELETE FROM {t} WHERE id=?", (aid,))
    for m in mids:
        db.x("DELETE FROM meeting_events WHERE meeting_id=?", (m,))
    for k in jids + mids + rids + [aid]:
        db.x("DELETE FROM idempotency WHERE key LIKE ?", (f"%{k}%",))
    for t in ACCOUNT_TABLES:
        c = cols(fresh, t)
        where = "account_id=?" if "account_id" in c else "id=?"
        for r in fresh.q(f"SELECT * FROM {t} WHERE {where}", (aid,)):
            r.pop("rid", None) if t in ("interactions", "tool_executions") and False else None
            ks = list(r)
            db.x(f"INSERT INTO {t}({','.join(ks)}) VALUES({','.join('?' * len(ks))})", tuple(r[k] for k in ks))
    for m in mids:
        for r in fresh.q("SELECT * FROM meeting_events WHERE meeting_id=?", (m,)):
            r.pop("id", None)
            db.x(f"INSERT INTO meeting_events({','.join(r)}) VALUES({','.join('?' * len(r))})", tuple(r.values()))
    start = db.one("SELECT value FROM settings WHERE key='session_start'")["value"]
    db.x("INSERT OR REPLACE INTO settings(key,value) VALUES('clock',?)", (start,))
    return f"{name}'s messages, tasks, recommendations and journey were reset. The demo clock returned to {start[:10]}."
