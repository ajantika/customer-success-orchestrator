"""Application services: the only entry points the UI (and tests) use to cause side effects.

Rendering a page never calls these. They run only from button callbacks / form submits.
"""
from __future__ import annotations

import json
import statistics
from datetime import timedelta

from . import rules
from .agent import run_agent
from .db import DB, from_iso, to_iso
from .models import ACTIVE_STATES, PRODUCTS, TERMINAL
from .tools import ToolContext, execute_tool


# ---------------------------------------------------------------- triggers ---
def run_onboarding_check(db: DB, account_id: str, journey_id: str, mode: str = "scripted", llm: dict | None = None) -> dict:
    ref = f"check:{journey_id}:{to_iso(db.now())}"
    return run_agent(db, account_id, journey_id, {"type": "onboarding_check", "ref": ref}, mode, llm)


def handle_customer_message(db: DB, account_id: str, journey_id: str, channel: str, text: str, mode: str = "scripted",
                            llm: dict | None = None, submission_id: str | None = None) -> dict:
    ing = rules.ingest_customer_message(db, account_id, journey_id, channel, text, submission_id)
    if ing.get("deduplicated"):
        return {"deduplicated": True, "outcome": "completed", "summary": "Duplicate submission ignored (idempotent).", "run_id": None, "error": None, "steps": 0}
    trig = {"type": "customer_reply", "ref": f"reply:{ing['interaction_id']}", "interaction_id": ing["interaction_id"],
            "intent": ing["signals"]["intent"], "channel": channel, "text": text.strip()[:1000]}
    out = run_agent(db, account_id, journey_id, trig, mode, llm)
    out["interaction_id"] = ing["interaction_id"]
    return out


def simulate_setup_complete(db: DB, account_id: str, product: str) -> list[str]:
    """Emit real synthetic product events for every incomplete milestone (and refresh the data sync)."""
    emitted = []
    pr = rules.progress(db, account_id, product)
    for m in pr["milestones"]:
        if not m["done"] and rules.add_event(db, account_id, product, m["key"]):
            emitted.append(m["key"])
    rules.add_event(db, account_id, product, "usage_session")
    rules.refresh_data(db, account_id)
    db.timeline(account_id, "system", "event", f"Product events received ({product}): {', '.join(emitted) or 'none new'}")
    return emitted


def advance_clock(db: DB, days: float = 0, hours: float = 0):
    t = db.advance(days, hours)
    # simulated nightly sync keeps data fresh, except for the account seeded with stale data
    db.x("UPDATE accounts SET data_refreshed_at=? WHERE scenario NOT IN ('stale_data')", (to_iso(t),))
    return t


# ------------------------------------------------------------ human queue ---
def assign_task(db: DB, task_id: str, assignee: str):
    t = db.one("SELECT * FROM human_tasks WHERE id=?", (task_id,))
    if not t or t["status"] == "resolved":
        raise ValueError("Task not open")
    db.update("human_tasks", task_id, assignee=assignee, status="assigned" if t["status"] == "open" else t["status"])
    db.timeline(t["account_id"], "human", "human_update", f"{task_id} assigned to {assignee}", t["journey_id"])


def set_task_status(db: DB, task_id: str, status: str):
    t = db.one("SELECT * FROM human_tasks WHERE id=?", (task_id,))
    if not t or t["status"] == "resolved" or status not in ("open", "assigned", "in_progress"):
        raise ValueError("Invalid status change")
    db.update("human_tasks", task_id, status=status)
    db.timeline(t["account_id"], "human", "human_update", f"{task_id} marked {status.replace('_', ' ')}", t["journey_id"])


def resolve_task(db: DB, task_id: str, note: str, simulate_fix: bool = False, mode: str = "scripted", llm: dict | None = None) -> dict:
    """Resolve the support task, then force a fresh progress check. Resolution never marks onboarding complete by itself."""
    note = (note or "").strip()
    if len(note) < 10:
        raise ValueError("A resolution note of at least 10 characters is required.")
    t = db.one("SELECT * FROM human_tasks WHERE id=?", (task_id,))
    if not t:
        raise ValueError("Unknown task")
    if t["status"] == "resolved":
        return {"outcome": "completed", "summary": "Task was already resolved.", "run_id": None, "deduplicated": True}
    now = to_iso(db.now())
    db.update("human_tasks", task_id, status="resolved", resolution_note=note, resolved_at=now)
    if t["case_id"]:
        db.x("UPDATE support_cases SET status='closed', resolved_at=? WHERE id=?", (now, t["case_id"]))
    db.timeline(t["account_id"], "human", "human_update", f"{task_id} resolved: {note}", t["journey_id"])
    rules.set_journey_state(db, t["journey_id"], "resolved_awaiting_progress_check", "support task resolved; fresh progress check required")
    if simulate_fix:
        pr = rules.progress(db, t["account_id"], t["product"])
        nm = pr["next_milestone"]
        if nm:
            rules.add_event(db, t["account_id"], t["product"], nm["key"])
    rules.refresh_data(db, t["account_id"])  # fresh sync before the check
    j = db.one("SELECT state FROM journeys WHERE id=?", (t["journey_id"],))
    if j["state"] in TERMINAL:
        return {"outcome": "completed", "summary": f"Task resolved; journey is {j['state']}, no check needed.", "run_id": None}
    trig = {"type": "progress_check", "ref": f"resolved:{task_id}", "task_id": task_id, "note": note}
    return run_agent(db, t["account_id"], t["journey_id"], trig, mode, llm)


# ---------------------------------------------------------- batch actions ---
def run_pending_actions(db: DB, mode: str = "scripted", llm: dict | None = None) -> list[dict]:
    out = []
    now = to_iso(db.now())
    for a in db.q("SELECT * FROM scheduled_actions WHERE status='pending' AND due_at<=? ORDER BY due_at, id", (now,)):
        j = db.one("SELECT * FROM journeys WHERE id=?", (a["journey_id"],))
        if j["state"] in TERMINAL or j["state"] == "waiting_for_human":
            db.update("scheduled_actions", a["id"], status="cancelled", note=f"journey is {j['state']}")
            db.guard("outreach_prevented", a["account_id"], a["journey_id"], f"reminder skipped: {j['state']}")
            out.append({"action": a["id"], "type": a["action_type"], "result": f"cancelled ({j['state']})"})
            continue
        if a["action_type"] == "resume_check":
            run_id = db.next_id("RUN")
            db.insert("agent_runs", id=run_id, account_id=a["account_id"], journey_id=a["journey_id"], mode="system", trigger="scheduled_resume",
                      trigger_ref=a["id"], started_at=now)
            r = execute_tool(ToolContext(db, run_id, a["account_id"]), "resume_journey",
                             {"account_id": a["account_id"], "journey_id": a["journey_id"], "reason": "Planned rollout date reached"}, "Scheduled resume.",
                             f"sched:{a['id']}")
            db.x("UPDATE agent_runs SET finished_at=?, steps=1, outcome=?, summary=? WHERE id=?",
                 (now, "completed" if r["ok"] else "error", "Resumed journey" if r["ok"] else r["error"]["message"], run_id))
            db.update("scheduled_actions", a["id"], status="executed", note="resumed" if r["ok"] else r["error"]["message"])
            out.append({"action": a["id"], "type": "resume_check", "result": "resumed" if r["ok"] else r["error"]["message"]})
        else:
            res = run_agent(db, a["account_id"], a["journey_id"], {"type": "scheduled_reminder", "ref": f"sched:{a['id']}"}, mode, llm)
            db.update("scheduled_actions", a["id"], status="executed", note=res["summary"][:200])
            out.append({"action": a["id"], "type": "setup_reminder", "result": res["summary"]})
    return out


def daily_scan(db: DB) -> list[dict]:
    """Scripted scan over every open journey. Shows rules protecting customers at scale."""
    rows = []
    for j in db.q("SELECT j.*, a.name FROM journeys j JOIN accounts a ON a.id=j.account_id WHERE j.state NOT IN ('completed','opted_out','waiting_for_human') ORDER BY j.id"):
        before = db.one("SELECT COUNT(*) n FROM interactions WHERE account_id=? AND actor='agent' AND kind='message'", (j["account_id"],))["n"]
        r = run_agent(db, j["account_id"], j["id"], {"type": "onboarding_check", "ref": f"scan:{j['id']}:{to_iso(db.now())}"}, "scripted")
        after = db.one("SELECT COUNT(*) n FROM interactions WHERE account_id=? AND actor='agent' AND kind='message'", (j["account_id"],))["n"]
        rows.append({"Account": j["name"], "Product": j["product"], "Message sent": "Yes" if after > before else "No", "Outcome": r["summary"]})
    return rows


# --------------------------------------------------------------- metrics ---
def pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "n/a"


def session_metrics(db: DB) -> dict:
    g = lambda kind: db.one("SELECT COUNT(*) n FROM guard_log WHERE origin='session' AND kind=?", (kind,))["n"]
    tool = db.one("SELECT COUNT(*) n, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) err, SUM(deduplicated) dup FROM tool_executions WHERE origin='session'")
    start = db.one("SELECT value FROM settings WHERE key='session_start'")["value"]
    open_at_start = int(db.one("SELECT value FROM settings WHERE key='open_at_start'")["value"])
    done = db.one("SELECT COUNT(*) n FROM journeys WHERE state='completed' AND completed_at>=?", (start,))["n"]
    return {
        "runs": db.one("SELECT COUNT(*) n FROM agent_runs WHERE origin='session'")["n"],
        "agent_messages": db.one("SELECT COUNT(*) n FROM interactions WHERE origin='session' AND actor='agent' AND kind='message'")["n"],
        "customer_messages": db.one("SELECT COUNT(*) n FROM interactions WHERE origin='session' AND actor='customer'")["n"],
        "tool_calls": tool["n"] or 0, "tool_errors": tool["err"] or 0,
        "duplicates_prevented": g("duplicate_prevented"),
        "outreach_prevented": g("outreach_blocked") + g("outreach_prevented") + g("repeat_guidance_prevented"),
        "policy_overrides": g("policy_override_rejected"),
        "handoffs_created": db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"],
        "handoffs_resolved": db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session' AND status='resolved'")["n"],
        "journeys_completed": done, "open_at_start": open_at_start,
        "opted_out": db.one("SELECT COUNT(*) n FROM journeys WHERE state='opted_out' AND updated_at>=? AND origin='seed'", (start,))["n"],
        "error_codes": db.q("SELECT error, COUNT(*) n FROM tool_executions WHERE origin='session' AND ok=0 GROUP BY error ORDER BY n DESC"),
    }


def seeded_metrics(db: DB) -> dict:
    rows = []
    for prod in PRODUCTS:
        started = db.q("SELECT j.account_id, j.state, r.planned_start FROM journeys j JOIN rollout_plans r ON r.account_id=j.account_id AND r.product=j.product "
                       "WHERE j.product=? AND j.origin='seed' AND r.planned_start<=?", (prod, db.one("SELECT value v FROM settings WHERE key='session_start'")["v"]))
        snap = json.loads(db.one("SELECT value FROM settings WHERE key='seed_states'")["value"])
        completed = snap.get(prod, {}).get("completed", 0)
        rows.append({"product": prod, "rollout_started": len(started), "completed": completed})
    gaps: dict[str, list[float]] = {p: [] for p in PRODUCTS}
    for r in db.q("SELECT e.product, MIN(e.ts) first, r.planned_start FROM product_events e JOIN rollout_plans r ON r.account_id=e.account_id AND r.product=e.product "
                  "WHERE e.origin='seed' AND e.event_type!='usage_session' GROUP BY e.account_id, e.product"):
        gaps[r["product"]].append((from_iso(r["first"]) - from_iso(r["planned_start"])).total_seconds() / 86400)
    ttm = [{"product": p, "accounts": len(v), "median_days": round(statistics.median(v), 1) if v else None} for p, v in gaps.items()]
    tasks = db.q("SELECT team, status, COUNT(*) n FROM human_tasks WHERE origin='seed' GROUP BY team, status")
    return {"completion": rows, "time_to_first": ttm, "handoffs": tasks, "states": json.loads(db.one("SELECT value FROM settings WHERE key='seed_states'")["value"])}


def snapshot_seed(db: DB):
    """Record baseline counts so seeded history stays separate from session activity."""
    db.x("INSERT OR REPLACE INTO settings(key,value) VALUES('session_start',?)", (to_iso(db.now()),))
    snap: dict = {}
    for r in db.q("SELECT product, state, COUNT(*) n FROM journeys GROUP BY product, state"):
        snap.setdefault(r["product"], {})[r["state"]] = r["n"]
    db.x("INSERT OR REPLACE INTO settings(key,value) VALUES('seed_states',?)", (json.dumps(snap),))
    open_n = db.one("SELECT COUNT(*) n FROM journeys WHERE state NOT IN ('completed','opted_out')")["n"]
    db.x("INSERT OR REPLACE INTO settings(key,value) VALUES('open_at_start',?)", (str(open_n),))


def overview_counts(db: DB) -> dict:
    return {
        "monitored": db.one("SELECT COUNT(DISTINCT account_id) n FROM journeys WHERE state NOT IN ('completed','opted_out')")["n"],
        "active": db.one("SELECT COUNT(*) n FROM journeys WHERE state IN ('monitoring','guidance_sent','waiting_for_customer','resolved_awaiting_progress_check')")["n"],
        "waiting_help": db.one("SELECT COUNT(DISTINCT account_id) n FROM human_tasks WHERE status!='resolved'")["n"],
        "open_handoffs": db.one("SELECT COUNT(*) n FROM human_tasks WHERE status!='resolved'")["n"],
        "completed": db.one("SELECT COUNT(*) n FROM journeys WHERE state='completed'")["n"],
    }


def priority_accounts(db: DB, limit: int = 8) -> list[dict]:
    out = []
    for j in db.q("SELECT j.*, a.name, a.goal FROM journeys j JOIN accounts a ON a.id=j.account_id WHERE j.state NOT IN ('completed','opted_out')"):
        score, reasons = 0, []
        if rules.has_unanswered_inbound(db, j["account_id"]):
            score += 50; reasons.append("Customer message waiting for a reply")
        t = db.one("SELECT priority FROM human_tasks WHERE journey_id=? AND status!='resolved'", (j["id"],))
        if t:
            score += {"high": 40, "medium": 30, "low": 20}[t["priority"]]; reasons.append(f"Open handoff ({t['priority']})")
        e = rules.evaluate_outreach(db, j["id"])
        codes = e.codes()
        if "missing_data" in codes or "stale_data" in codes:
            score += 25; reasons.append("Missing or stale data - needs review")
        if e.allowed:
            score += 20; reasons.append("Stalled and eligible for outreach")
        if score:
            out.append({"journey_id": j["id"], "account_id": j["account_id"], "Account": j["name"], "Product": j["product"],
                        "State": j["state"], "Why": "; ".join(reasons), "score": score})
    return sorted(out, key=lambda r: -r["score"])[:limit]
