"""Session-scoped SQLite repository layer.

Each Streamlit session builds its own in-memory database, so visitors never share state.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from .models import Settings

SCHEMA = """
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE seq(prefix TEXT PRIMARY KEY, n INTEGER);
CREATE TABLE accounts(id TEXT PRIMARY KEY, name TEXT, segment TEXT, goal TEXT, scenario TEXT,
  needs_directory INTEGER DEFAULT 0, data_refreshed_at TEXT, lifecycle TEXT DEFAULT 'onboarding', owner TEXT, solutions_architect TEXT);
CREATE TABLE contacts(id TEXT PRIMARY KEY, account_id TEXT, name TEXT, email TEXT, role TEXT,
  is_admin INTEGER, opted_out INTEGER DEFAULT 0, preferred_channel TEXT DEFAULT 'email', consent INTEGER DEFAULT 1);
CREATE TABLE subscriptions(id TEXT PRIMARY KEY, account_id TEXT, product TEXT, bundle INTEGER, status TEXT);
CREATE TABLE rollout_plans(account_id TEXT, product TEXT, planned_start TEXT, PRIMARY KEY(account_id, product));
CREATE TABLE product_events(id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, product TEXT, event_type TEXT, ts TEXT, origin TEXT);
CREATE TABLE support_cases(id TEXT PRIMARY KEY, account_id TEXT, product TEXT, subject TEXT, category TEXT,
  status TEXT, blocking INTEGER, created_at TEXT, resolved_at TEXT, origin TEXT);
CREATE TABLE interactions(rid INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, account_id TEXT, contact_id TEXT, journey_id TEXT,
  channel TEXT, actor TEXT, kind TEXT, body TEXT, sources TEXT DEFAULT '[]', signals TEXT DEFAULT '{}', ts TEXT, origin TEXT);
CREATE TABLE journeys(id TEXT PRIMARY KEY, account_id TEXT, product TEXT, state TEXT, paused_until TEXT,
  attempted_docs TEXT DEFAULT '[]', started_at TEXT, updated_at TEXT, completed_at TEXT, origin TEXT);
CREATE TABLE scheduled_actions(id TEXT PRIMARY KEY, account_id TEXT, journey_id TEXT, action_type TEXT,
  due_at TEXT, status TEXT, created_at TEXT, note TEXT, origin TEXT);
CREATE TABLE human_tasks(id TEXT PRIMARY KEY, account_id TEXT, journey_id TEXT, product TEXT, issue TEXT, category TEXT,
  priority TEXT, team TEXT, status TEXT, assignee TEXT, context TEXT, resolution_note TEXT, created_at TEXT,
  resolved_at TEXT, case_id TEXT, origin TEXT);
CREATE TABLE agent_runs(id TEXT PRIMARY KEY, account_id TEXT, journey_id TEXT, mode TEXT, model TEXT, trigger TEXT,
  trigger_ref TEXT, started_at TEXT, finished_at TEXT, steps INTEGER DEFAULT 0, outcome TEXT, summary TEXT, error TEXT, origin TEXT);
CREATE TABLE tool_executions(rid INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, run_id TEXT, account_id TEXT, tool TEXT,
  args TEXT, result TEXT, ok INTEGER, error TEXT, rationale TEXT, deduplicated INTEGER DEFAULT 0, ts TEXT, origin TEXT);
CREATE TABLE idempotency(key TEXT PRIMARY KEY, tool TEXT, result TEXT, created_at TEXT);
CREATE TABLE guard_log(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, account_id TEXT, journey_id TEXT, detail TEXT, ts TEXT, origin TEXT);
CREATE TABLE eval_results(id INTEGER PRIMARY KEY AUTOINCREMENT, suite TEXT, name TEXT, passed INTEGER, detail TEXT, ran_at TEXT);
CREATE TABLE ratings(id INTEGER PRIMARY KEY AUTOINCREMENT, interaction_id TEXT, kind TEXT DEFAULT 'message', relevance INTEGER, groundedness INTEGER,
  correctness INTEGER, instruction_following INTEGER, helpfulness INTEGER, clarity INTEGER, timing INTEGER, role_fit INTEGER,
  prerequisite_fit INTEGER, usefulness INTEGER, note TEXT, ts TEXT);
CREATE TABLE meetings(id TEXT PRIMARY KEY, account_id TEXT, owner TEXT, solutions_architect TEXT, starts_at TEXT, purpose TEXT,
  attendee_roles TEXT, status TEXT, previous_start TEXT, origin TEXT);
CREATE TABLE courses(id TEXT PRIMARY KEY, product TEXT, topic TEXT, title TEXT, persona TEXT, difficulty TEXT, prerequisites TEXT,
  skills TEXT, format TEXT, duration_min INTEGER, paid INTEGER, price_note TEXT, availability TEXT, source_doc TEXT, source_section TEXT, updated_at TEXT);
CREATE TABLE learner_records(id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT, account_id TEXT, role TEXT, course_id TEXT,
  status TEXT, completed_at TEXT, record_updated_at TEXT, origin TEXT);
CREATE TABLE recommendations(id TEXT PRIMARY KEY, account_id TEXT, meeting_id TEXT, status TEXT, action_type TEXT, title TEXT, why_now TEXT,
  goal TEXT, talking_point TEXT, brief TEXT, evidence TEXT, learner_group TEXT, courses TEXT, unknowns TEXT, completeness TEXT,
  generation_mode TEXT, agent_version TEXT, dedupe_key TEXT, needs_refresh INTEGER DEFAULT 0, defer_until TEXT,
  content_original TEXT, content_current TEXT, created_at TEXT, updated_at TEXT, origin TEXT);
CREATE TABLE rec_feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, rec_id TEXT, account_id TEXT, meeting_id TEXT, reviewer TEXT, action TEXT,
  reason TEXT, note TEXT, original TEXT, revised TEXT, ts TEXT, origin TEXT);
CREATE TABLE learning_outcomes(id INTEGER PRIMARY KEY AUTOINCREMENT, rec_id TEXT, account_id TEXT, stage TEXT, learner_count INTEGER, ts TEXT, origin TEXT);
CREATE TABLE meeting_events(id INTEGER PRIMARY KEY AUTOINCREMENT, meeting_id TEXT, event TEXT, reviewer TEXT, ts TEXT, origin TEXT);
"""

ISO = "%Y-%m-%dT%H:%M:%S"


def to_iso(dt: datetime) -> str:
    return dt.strftime(ISO)


def from_iso(s: str) -> datetime:
    return datetime.strptime(s[:19], ISO)


class DB:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.origin = "session"
        self._settings: Settings | None = None

    # -- low level --------------------------------------------------------------
    def init_schema(self):
        self.conn.executescript(SCHEMA)

    def q(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        r = self.conn.execute(sql, params).fetchone()
        return dict(r) if r else None

    def x(self, sql: str, params: tuple = ()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def insert(self, table: str, **vals):
        if table in ORIGIN_TABLES and "origin" not in vals:
            vals["origin"] = self.origin
        cols = ",".join(vals)
        self.conn.execute(f"INSERT INTO {table}({cols}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))
        self.conn.commit()

    def update(self, table: str, row_id, **vals):
        sets = ",".join(f"{k}=?" for k in vals)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*vals.values(), row_id))
        self.conn.commit()

    def next_id(self, prefix: str, width: int = 3) -> str:
        row = self.one("SELECT n FROM seq WHERE prefix=?", (prefix,))
        n = (row["n"] if row else 0) + 1
        self.x("INSERT OR REPLACE INTO seq(prefix,n) VALUES(?,?)", (prefix, n))
        return f"{prefix}-{n:0{width}d}"

    # -- settings and clock -----------------------------------------------------
    def get_settings(self) -> Settings:
        if self._settings is None:
            row = self.one("SELECT value FROM settings WHERE key='policy'")
            self._settings = Settings(**json.loads(row["value"])) if row else Settings()
        return self._settings

    def save_settings(self, s: Settings):
        self.x("INSERT OR REPLACE INTO settings(key,value) VALUES('policy',?)", (s.model_dump_json(),))
        self._settings = s

    def now(self) -> datetime:
        return from_iso(self.one("SELECT value FROM settings WHERE key='clock'")["value"])

    def set_clock(self, dt: datetime):
        self.x("INSERT OR REPLACE INTO settings(key,value) VALUES('clock',?)", (to_iso(dt),))

    def advance(self, days: float = 0, hours: float = 0) -> datetime:
        t = self.now() + timedelta(days=days, hours=hours)
        self.set_clock(t)
        return t

    # -- logging helpers --------------------------------------------------------
    def timeline(self, account_id: str, actor: str, kind: str, body: str, journey_id: str | None = None,
                 contact_id: str | None = None, channel: str = "system", sources=None, signals=None) -> str:
        iid = self.next_id("INT", 4)
        self.insert("interactions", id=iid, account_id=account_id, contact_id=contact_id, journey_id=journey_id,
                    channel=channel, actor=actor, kind=kind, body=body, sources=json.dumps(sources or []),
                    signals=json.dumps(signals or {}), ts=to_iso(self.now()))
        return iid

    def guard(self, kind: str, account_id: str | None, journey_id: str | None, detail: str):
        self.insert("guard_log", kind=kind, account_id=account_id, journey_id=journey_id, detail=detail, ts=to_iso(self.now()))


ORIGIN_TABLES = {"meetings", "learner_records", "recommendations", "rec_feedback", "learning_outcomes", "meeting_events", "product_events", "support_cases", "interactions", "journeys", "scheduled_actions", "human_tasks",
                 "agent_runs", "tool_executions", "guard_log"}
