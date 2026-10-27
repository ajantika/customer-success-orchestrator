"""Business rules enforced in application code, independent of any LLM.

Nothing in this module calls a model. Tools consult these functions before acting,
so a scripted run and a live run face exactly the same constraints.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .db import DB, from_iso, to_iso
from .models import TERMINAL, STATE_LABEL, Settings, can_transition


# ---------------------------------------------------------------- progress ---
def milestone_defs(db: DB, account_id: str, product: str) -> list[dict]:
    acc = db.one("SELECT * FROM accounts WHERE id=?", (account_id,))
    out = []
    for m in db.get_settings().milestones.get(product, []):
        if not m.get("enabled", True):
            continue
        cond = m.get("applies_if")
        if cond and not (acc and acc.get(cond)):
            continue
        out.append(m)
    return out


def progress(db: DB, account_id: str, product: str) -> dict:
    ev = {r["event_type"]: r["ts"] for r in db.q(
        "SELECT event_type, MIN(ts) ts FROM product_events WHERE account_id=? AND product=? GROUP BY event_type", (account_id, product))}
    ms = []
    for m in milestone_defs(db, account_id, product):
        ms.append({"key": m["key"], "label": m["label"], "customer_label": m.get("customer_label") or m["label"], "done": m["key"] in ev, "done_at": ev.get(m["key"])})
    nxt = next((m for m in ms if not m["done"]), None)
    last = max((m["done_at"] for m in ms if m["done_at"]), default=None)
    now = db.now()

    def _count(kind: str, lo: int, hi: int) -> int:
        return db.one("SELECT COUNT(*) n FROM product_events WHERE account_id=? AND product=? AND event_type=? AND ts>? AND ts<=?",
                      (account_id, product, kind, to_iso(now - timedelta(days=hi)), to_iso(now - timedelta(days=lo))))["n"]

    acc = db.one("SELECT data_refreshed_at FROM accounts WHERE id=?", (account_id,))
    as_of = acc["data_refreshed_at"] if acc else None
    stale = (as_of is None) or (db.now() - from_iso(as_of) > timedelta(days=db.get_settings().stale_data_days))
    return {"product": product, "milestones": ms, "complete": bool(ms) and nxt is None, "next_milestone": nxt,
            "last_progress_at": last, "done_count": sum(m["done"] for m in ms), "total": len(ms),
            "data_as_of": as_of, "stale": stale,
            "usage_recent": _count("usage_session", 0, 14), "usage_prior": _count("usage_session", 14, 44),
            "workflow_recent": _count("shared_workflow_used", 0, 14), "workflow_prior": _count("shared_workflow_used", 14, 44)}


def add_event(db: DB, account_id: str, product: str, event_type: str, ts: datetime | None = None):
    if event_type != "usage_session" and db.one(
            "SELECT 1 x FROM product_events WHERE account_id=? AND product=? AND event_type=?", (account_id, product, event_type)):
        return False
    db.insert("product_events", account_id=account_id, product=product, event_type=event_type, ts=to_iso(ts or db.now()))
    return True


def refresh_data(db: DB, account_id: str):
    db.x("UPDATE accounts SET data_refreshed_at=? WHERE id=?", (to_iso(db.now()), account_id))


# ------------------------------------------------------------- eligibility ---
@dataclass
class Check:
    code: str
    passed: bool
    message: str


@dataclass
class Eligibility:
    allowed: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def codes(self) -> list[str]:
        return [c.code for c in self.blockers]

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "checks": [c.__dict__ for c in self.checks]}


def admin_contact(db: DB, account_id: str) -> dict | None:
    return db.one("SELECT * FROM contacts WHERE account_id=? AND is_admin=1 ORDER BY id LIMIT 1", (account_id,))


def has_unanswered_inbound(db: DB, account_id: str) -> bool:
    last = db.one("SELECT actor FROM interactions WHERE account_id=? AND kind='message' AND actor IN ('agent','customer') "
                  "ORDER BY rid DESC LIMIT 1", (account_id,))
    return bool(last and last["actor"] == "customer")


def _proactive_times(db: DB, account_id: str) -> list[datetime]:
    rows = db.q("SELECT ts FROM interactions WHERE account_id=? AND actor='agent' AND kind='message' "
                "AND json_extract(signals,'$.message_kind')='proactive' ORDER BY rid", (account_id,))
    return [from_iso(r["ts"]) for r in rows]


def unanswered_proactive(db: DB, account_id: str) -> int:
    rows = db.q("SELECT actor, json_extract(signals,'$.message_kind') mk FROM interactions WHERE account_id=? "
                "AND kind='message' AND actor IN ('agent','customer') ORDER BY rid DESC", (account_id,))
    n = 0
    for r in rows:
        if r["actor"] == "customer":
            break
        if r["mk"] == "proactive":
            n += 1
    return n


def open_blockers(db: DB, account_id: str, product: str, journey_id: str | None = None) -> dict:
    cases = db.q("SELECT * FROM support_cases WHERE account_id=? AND product=? AND status='open' AND blocking=1", (account_id, product))
    tasks = db.q("SELECT * FROM human_tasks WHERE account_id=? AND product=? AND status!='resolved'", (account_id, product))
    return {"cases": cases, "tasks": tasks}


def evaluate_outreach(db: DB, journey_id: str, kind: str = "proactive", settings: Settings | None = None,
                      now: datetime | None = None) -> Eligibility:
    """Decide whether the platform may contact the customer about this journey.

    kind: proactive (agent-initiated), reply (answers a customer message), status_update, confirmation.
    """
    st = settings or db.get_settings()
    now = now or db.now()
    j = db.one("SELECT * FROM journeys WHERE id=?", (journey_id,))
    if not j:
        return Eligibility(False, [Check("journey_exists", False, "Journey not found")])
    aid, prod = j["account_id"], j["product"]
    checks: list[Check] = []
    add = lambda code, ok, msg: checks.append(Check(code, bool(ok), msg))

    contact = admin_contact(db, aid)
    plan = db.one("SELECT planned_start FROM rollout_plans WHERE account_id=? AND product=?", (aid, prod))
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    missing = []
    if not contact or not contact.get("email"):
        missing.append("administrator contact email")
    if not plan:
        missing.append("rollout plan")
    if not (acc and acc.get("goal")):
        missing.append("customer goal")
    add("missing_data", not missing, "Essential data present" if not missing else f"Missing essential data: {', '.join(missing)}")

    opted = bool(contact and contact["opted_out"]) or j["state"] == "opted_out"
    add("opt_out", not opted, "Customer has not opted out" if not opted else "Customer opted out of messages")
    add("journey_open", j["state"] not in TERMINAL,
        f"Journey is {STATE_LABEL[j['state']].lower()}" if j["state"] in TERMINAL else "Journey is open")

    if kind in ("reply", "status_update", "confirmation"):
        if kind == "reply":
            add("inbound_waiting", has_unanswered_inbound(db, aid), "A customer message is waiting for a reply"
                if has_unanswered_inbound(db, aid) else "No unanswered customer message")
        return Eligibility(all(c.passed for c in checks), checks)

    # proactive-only checks
    as_of = acc["data_refreshed_at"] if acc else None
    fresh = bool(as_of) and now - from_iso(as_of) <= timedelta(days=st.stale_data_days)
    add("stale_data", fresh, "Product data is fresh" if fresh else f"Product data is older than {st.stale_data_days} days (last refresh {as_of or 'never'})")

    pr = progress(db, aid, prod)
    add("setup_incomplete", not pr["complete"], "Setup is not complete" if not pr["complete"] else "Setup is already complete")

    start = from_iso(plan["planned_start"]) if plan else None
    paused_until = from_iso(j["paused_until"]) if j["paused_until"] else None
    started = bool(start) and start <= now and (paused_until is None or paused_until <= now)
    if not start:
        add("rollout_started", False, "No rollout date on file")
    elif start > now:
        add("rollout_started", False, f"Rollout planned for {start:%b %d}, not started yet")
    elif paused_until and paused_until > now:
        add("rollout_started", False, f"Customer asked to wait until {paused_until:%b %d}")
    else:
        add("rollout_started", True, f"Rollout started {start:%b %d}")

    bl = open_blockers(db, aid, prod, journey_id)
    blocked = j["state"] == "waiting_for_human" or (st.stop_on_blocking_case and (bl["cases"] or bl["tasks"]))
    add("no_blocking_case", not blocked, "No open blocking support case" if not blocked else "A blocking support case or human task is open")

    if started:
        base = max(start, from_iso(pr["last_progress_at"])) if pr["last_progress_at"] else start
        idle = (now - base).days
        add("stalled", idle >= st.stall_threshold_days,
            f"No milestone progress for {idle} days (threshold {st.stall_threshold_days})")
    else:
        add("stalled", False, "Stall check not applicable before rollout start")

    times = _proactive_times(db, aid)
    last7 = [t for t in times if now - t <= timedelta(days=7)]
    gap_ok = not times or (now - times[-1]) >= timedelta(hours=st.min_hours_between_messages)
    add("frequency", len(last7) < st.max_messages_per_7d and gap_ok,
        f"{len(last7)} of {st.max_messages_per_7d} proactive messages used in 7 days; minimum gap {st.min_hours_between_messages}h")
    un = unanswered_proactive(db, aid)
    add("unanswered_cap", un < st.max_unanswered_messages, f"{un} consecutive unanswered messages (cap {st.max_unanswered_messages})")
    return Eligibility(all(c.passed for c in checks), checks)


# ------------------------------------------------------ state transitions ---
def set_journey_state(db: DB, journey_id: str, new: str, reason: str, **extra) -> tuple[bool, str | None]:
    j = db.one("SELECT * FROM journeys WHERE id=?", (journey_id,))
    if not j:
        return False, "journey not found"
    if j["state"] == new:
        return True, None
    if not can_transition(j["state"], new):
        return False, f"transition {j['state']} -> {new} is not allowed"
    vals = {"state": new, "updated_at": to_iso(db.now()), **extra}
    if new == "completed":
        vals["completed_at"] = to_iso(db.now())
    db.update("journeys", journey_id, **vals)
    from .models import PRODUCT_LABEL
    db.timeline(j["account_id"], "system", "tool_action",
                f"{PRODUCT_LABEL[j['product']]} setup status changed from “{STATE_LABEL[j['state']]}” to “{STATE_LABEL[new]}” ({reason.replace('_', ' ')}).", journey_id)
    return True, None


def schedule(db: DB, account_id: str, journey_id: str, action_type: str, due: datetime, note: str) -> str:
    aid = db.next_id("ACT")
    db.insert("scheduled_actions", id=aid, account_id=account_id, journey_id=journey_id, action_type=action_type,
              due_at=to_iso(due), status="pending", created_at=to_iso(db.now()), note=note)
    return aid


def cancel_pending(db: DB, journey_id: str, reason: str, types: tuple[str, ...] = ("setup_reminder",)) -> int:
    j = db.one("SELECT account_id, product FROM journeys WHERE id=?", (journey_id,))
    ph = ",".join("?" * len(types))
    rows = db.q(f"SELECT id FROM scheduled_actions WHERE journey_id=? AND status='pending' AND action_type IN ({ph})", (journey_id, *types))
    for r in rows:
        db.update("scheduled_actions", r["id"], status="cancelled", note=reason)
    if rows and j:
        db.timeline(j["account_id"], "system", "tool_action", f"Cancelled {len(rows)} pending {j['product']} reminder(s): {reason}", journey_id)
    return len(rows)


def apply_opt_out(db: DB, account_id: str):
    db.x("UPDATE contacts SET opted_out=1 WHERE account_id=?", (account_id,))
    for j in db.q("SELECT id, state FROM journeys WHERE account_id=? AND state NOT IN ('completed','opted_out')", (account_id,)):
        cancel_pending(db, j["id"], "customer opted out", ("setup_reminder", "resume_check"))
        set_journey_state(db, j["id"], "opted_out", "customer opted out")


# ------------------------------------------------- inbound message screening ---
_PATTERNS = [
    ("policy_override", r"ignore (all |any |the |your )?(previous|prior|above)? ?(instructions|rules|polic)|disregard|system prompt|you are now|"
                        r"override|reveal .*(prompt|key|password)|(refund|discount|credit)|change (my|our|the) (billing|plan|subscription|permission)|"
                        r"(send|email).*(all|every|other) (customers|accounts)|delete (all|the|every)|admin access|jailbreak"),
    ("opt_out", r"stop (sending|emailing|messag)|unsubscribe|do not contact|don'?t contact|opt out|remove me|no more (emails|messages)"),
    ("setup_complete", r"setup is (now )?(complete|done|finished)|finished (the )?setup|all set up|completed (the )?setup|we'?re (all )?done"),
    ("tried_steps", r"already tried|tried (all|those|these|that|them)|still (fails|failing|not working|broken)|didn'?t work|did not work"),
    ("issue", r"directory|sync|failing|fails|error|can'?t connect|cannot connect|trouble|not working|stuck|broken"),
    ("rollout_later", r"next (month|quarter|week)|rollout starts|starts in|not yet|later|after (the )?(holidays|launch)"),
    ("not_started", r"haven'?t started|not started|where (do|should) i start|how (do|can) i (get )?start|get started"),
]


_ERRORS = [
    ("authentication", r"authenticat|auth(orization)? (error|fail)|log ?in (fail|error)|sign.?in (fail|error)|password|credential|denied|unauthori[sz]ed|\b40[13]\b|token (expired|invalid)"),
    ("timeout", r"time[sd]?.?out|timed out|unreachable|cannot be reached|can'?t reach|port 636|firewall|connection refused"),
    ("no_groups", r"no groups|groups? (don'?t|do not|not|aren'?t|isn'?t) (sync|show|appear)|nothing (syncs|syncing)"),
    ("attribute_mapping", r"attribute|mapping|missing email|email field"),
]


def detect_error_type(text: str) -> str | None:
    t = (text or "").lower()
    return next((k for k, pat in _ERRORS if re.search(pat, t)), None)


def classify_message(text: str) -> dict:
    """Keyword screen of an inbound message. Output is a hint; policies are enforced in tools regardless."""
    t = text.lower()
    et = detect_error_type(text)
    for intent, pat in _PATTERNS:
        if re.search(pat, t):
            out = {"intent": "issue_directory" if intent == "issue" else intent, "screen": "keyword rules"}
            if out["intent"] == "issue_directory" and et:
                out["error_type"] = et
            return out
    if et:
        return {"intent": "issue_directory", "screen": "keyword rules", "error_type": et}
    return {"intent": "unknown", "screen": "keyword rules"}


def ingest_customer_message(db: DB, account_id: str, journey_id: str, channel: str, text: str, submission_id: str | None = None) -> dict:
    """Store an inbound message idempotently. Messages are untrusted data; this function never acts on their content
    except to record keyword signals and what the customer says they already tried."""
    if submission_id:
        prior = db.one("SELECT result FROM idempotency WHERE key=?", (f"customer:{submission_id}",))
        if prior:
            db.guard("duplicate_prevented", account_id, journey_id, f"customer message {submission_id} resubmitted")
            return {**json.loads(prior["result"]), "deduplicated": True}
    text = (text or "").strip()[:1000]
    if not text:
        raise ValueError("empty message")
    contact = admin_contact(db, account_id)
    sig = classify_message(text)
    if sig["intent"] == "policy_override":
        db.guard("policy_override_rejected", account_id, journey_id, text[:120])
    if sig["intent"] == "tried_steps":
        last = db.one("SELECT signals FROM interactions WHERE account_id=? AND journey_id=? AND actor='agent' AND kind='message' "
                      "ORDER BY rid DESC LIMIT 1", (account_id, journey_id))
        docs = json.loads(last["signals"]).get("guidance_docs", []) if last else []
        j = db.one("SELECT attempted_docs FROM journeys WHERE id=?", (journey_id,))
        merged = sorted(set(json.loads(j["attempted_docs"])) | set(docs))
        db.update("journeys", journey_id, attempted_docs=json.dumps(merged))
        sig["attempted_docs"] = docs
    iid = db.timeline(account_id, "customer", "message", text, journey_id, contact["id"] if contact else None, channel, signals=sig)
    out = {"interaction_id": iid, "signals": sig}
    if submission_id:
        db.x("INSERT OR IGNORE INTO idempotency(key,tool,result,created_at) VALUES(?,?,?,?)",
             (f"customer:{submission_id}", "ingest", json.dumps(out), to_iso(db.now())))
    return out


# ------------------------------------------------ plain-language decision ---
RULE_LABEL = {
    "missing_data": "Essential customer information is on file", "opt_out": "Customer has not opted out", "journey_open": "Setup journey is still open",
    "stale_data": "Product data is up to date", "setup_incomplete": "Setup is not yet complete", "rollout_started": "Rollout has started",
    "no_blocking_case": "No support issue is blocking", "stalled": "Setup progress has stalled long enough", "frequency": "Message limits allow another message",
    "unanswered_cap": "Earlier messages were answered", "inbound_waiting": "A customer message is waiting",
}


def plain_decision(db: DB, journey_id: str) -> dict:
    """What the system will do about proactive setup outreach for this journey, in plain words. Detailed rules go in 'details'."""
    j = db.one("SELECT * FROM journeys WHERE id=?", (journey_id,))
    st = db.get_settings()
    now = db.now()
    el = evaluate_outreach(db, journey_id)
    blocked = {c.code: c for c in el.checks if not c.passed}
    pr = progress(db, j["account_id"], j["product"])
    plan = db.one("SELECT planned_start FROM rollout_plans WHERE account_id=? AND product=?", (j["account_id"], j["product"]))
    when_ = lambda iso: from_iso(iso).strftime("%B ") + str(from_iso(iso).day)
    details = [{"rule": RULE_LABEL.get(c.code, c.code.replace("_", " ")), "met": c.passed, "note": c.message} for c in el.checks]
    if j["state"] == "opted_out" or "opt_out" in blocked:
        h, n, tone = "The customer asked not to be contacted, so no messages will be sent.", "Respect the opt-out. Reach out only if the customer contacts you.", "wait"
    elif j["state"] == "completed" or pr["complete"]:
        h, n, tone = "Setup is complete, so setup reminders have stopped.", "Setup is complete. Check whether the team is regularly using the intended workflow.", "ok"
    elif "missing_data" in blocked:
        h, n, tone = "Essential information is missing, so the assistant will not guess.", "Add the missing information before deciding whether to reach out.", "attention"
    elif "stale_data" in blocked:
        h, n, tone = "Usage data is out of date. Refresh it before deciding whether outreach is needed.", "Refresh the product data, then check this customer again.", "attention"
    elif "no_blocking_case" in blocked:
        h, n, tone = "Support is working on a blocker, so automated reminders are paused.", "Follow the support task. Setup reminders resume after it is resolved.", "wait"
    elif "rollout_started" in blocked:
        pu = j["paused_until"]
        if plan and from_iso(plan["planned_start"]) > now:
            h, n, tone = f"Rollout starts on {when_(plan['planned_start'])}, so proactive setup reminders should wait.", "No action needed until the rollout starts. The customer can still ask for help.", "wait"
        elif pu:
            h, n, tone = f"The customer asked to wait until {when_(pu)}, so proactive reminders should wait.", "No action needed until then. The customer can still ask for help.", "wait"
        else:
            h, n, tone = "There is no rollout date on file, so the assistant will not start outreach.", "Confirm the customer's rollout plan.", "attention"
    elif "frequency" in blocked:
        h, n, tone = "A message was sent recently, so the assistant will wait before contacting the customer again.", "Wait for a reply or for the message limit to reset.", "wait"
    elif "unanswered_cap" in blocked:
        h, n, tone = "Earlier messages have not been answered, so the assistant has stopped sending reminders.", "Consider a different channel or a call.", "attention"
    elif "stalled" in blocked:
        nm = pr["next_milestone"]["customer_label"] if pr["next_milestone"] else "the next step"
        h, n, tone = f"Setup is progressing. The assistant will offer help if there is no progress for {st.stall_threshold_days} days.", f"Next setup step: {nm}.", "ok"
    else:
        nm = pr["next_milestone"]["customer_label"] if pr["next_milestone"] else "the next step"
        h, n, tone = "Setup has stalled, so the assistant can offer help.", f"Check this customer's setup to send guidance for: {nm}.", "attention"
    return {"headline": h, "next_step": n, "tone": tone, "details": details, "allowed": el.allowed}
