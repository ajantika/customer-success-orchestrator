"""Agent tools: validated inputs/outputs, account-boundary enforcement and real state changes.

Every tool returns a ToolResult dict. A failure is always explicit (ok=False with an error code),
so callers (scripted or live) cannot claim an action succeeded when it did not.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import rules
from .db import DB, from_iso, to_iso
from .models import PRODUCTS, STATE_LABEL, can_transition
from .retrieval import SUPPORT_THRESHOLD, get_retriever


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


ONBOARDING_TOOLS = {"get_customer_context", "get_setup_progress", "get_interaction_history", "search_documentation", "check_support_cases",
                    "send_guidance", "pause_journey", "resume_journey", "create_handoff", "update_journey_status"}
TEAM_TOOLS = {"get_meeting_context", "get_customer_context", "get_setup_progress", "get_learning_progress", "search_training_catalog",
              "search_documentation", "get_account_blockers", "check_support_cases", "save_recommendation"}
POLICY_CODES = {"policy_blocked", "repeat_guidance", "account_boundary", "tool_not_permitted", "completion_not_supported", "invalid_transition",
                "blocked", "invalid_citation", "previously_dismissed", "deferred_recommendation", "already_completed", "prerequisite_unmet",
                "unsupported_evidence", "meeting_not_active", "paid_needs_justification", "not_permitted"}
REVIEWERS = ["Riley Chen", "Jamie Ortiz", "Sasha Imani", "Morgan Ellis", "Devon Park"]  # synthetic identities
DISMISS_REASONS = ["Wrong timing", "Customer already trained", "Technical blocker", "Irrelevant recommendation", "Missing information", "Duplicate recommendation"]


@dataclass
class ToolContext:
    db: DB
    run_id: str | None
    account_id: str  # the single account this run may touch
    actor: str = "agent"  # "agent" or "human" (review actions)
    allowed: set[str] | None = None  # explicit allow-list for this run; None = unrestricted (tests, human actions)
    mode: str = "demo"
    retrieved: set[str] | None = None  # documents surfaced by search in this run; citations are checked against them
    retrieved_sections: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)  # evidence items gathered in this run, by ID


# ------------------------------------------------------------------ schemas ---
class In(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(description="Account ID such as ACC-001. Must be the account this run is about.")


class MutIn(In):
    idempotency_key: str | None = Field(None, description="Set by the runtime. Do not provide.")


Product = Literal["tasks", "docs", "support"]


class CtxIn(In):
    journey_id: str | None = Field(None, description="Journey ID to evaluate outreach eligibility for.")


class CtxOut(BaseModel):
    account: dict
    products: list[dict]
    rollout: list[dict]
    journeys: list[dict]
    contact: dict | None
    eligibility: dict | None
    data_as_of: str | None
    clock: str


class ProgIn(In):
    product: Product


class ProgOut(BaseModel):
    product: str
    milestones: list[dict]
    complete: bool
    next_milestone: dict | None
    done_count: int
    total: int
    last_progress_at: str | None
    data_as_of: str | None
    stale: bool
    usage_recent: int = 0
    usage_prior: int = 0
    workflow_recent: int = 0
    workflow_prior: int = 0
    evidence: list[dict] = []


class HistIn(In):
    journey_id: str | None = None
    limit: int = Field(12, ge=1, le=30)


class HistOut(BaseModel):
    messages: list[dict]
    attempted_doc_ids: list[str]
    guidance_doc_ids: list[str]
    troubleshooting_replies: int
    last_customer_message_id: str | None


class SearchIn(In):
    query: str = Field(min_length=3, max_length=300)
    product: Product | None = None
    top_k: int = Field(3, ge=1, le=5)
    exclude_doc_ids: list[str] = []


class SearchOut(BaseModel):
    hits: list[dict]
    supported: bool
    note: str


class CasesIn(In):
    product: Product | None = None


class CasesOut(BaseModel):
    open_cases: list[dict]
    open_tasks: list[dict]
    blocking: bool


class SendIn(MutIn):
    journey_id: str
    contact_id: str
    channel: Literal["email", "chat"]
    kind: Literal["proactive", "reply", "status_update", "confirmation"]
    body: str = Field(min_length=10, max_length=2000)
    subject: str | None = Field(None, max_length=140)
    doc_ids: list[str] = []
    topic: Literal["clarify", "guidance", "troubleshooting"] | None = Field(None, description="Use clarify when asking the customer a question.")


class SendOut(BaseModel):
    interaction_id: str
    channel: str
    delivery: str
    next_reminder_at: str | None


class PauseIn(MutIn):
    journey_id: str
    reason: Literal["awaiting_human", "until_rollout", "customer_request"]
    resume_on: str | None = Field(None, description="ISO date to resume (YYYY-MM-DD).")


class StateOut(BaseModel):
    journey_id: str
    state: str
    detail: str


class ResumeIn(MutIn):
    journey_id: str
    reason: str = Field(min_length=3, max_length=200)


class HandoffIn(MutIn):
    journey_id: str
    issue: str = Field(min_length=5, max_length=200)
    category: Literal["integration", "configuration", "docs_gap", "other"]
    priority: Literal["low", "medium", "high"]
    summary: str = Field(min_length=10, max_length=800)
    attempted_doc_ids: list[str] = []


class HandoffOut(BaseModel):
    task_id: str
    case_id: str | None
    team: str
    existing: bool


class StatusIn(MutIn):
    journey_id: str
    new_state: Literal["monitoring", "guidance_sent", "waiting_for_customer", "completed", "opted_out"]
    reason: str = Field(min_length=3, max_length=200)


# ------------------------------------------------------------------ helpers ---
def _journey(ctx: ToolContext, account_id: str, journey_id: str) -> dict:
    j = ctx.db.one("SELECT * FROM journeys WHERE id=?", (journey_id,))
    if not j:
        raise ToolError("not_found", f"Unknown journey {journey_id}")
    if j["account_id"] != account_id:
        raise ToolError("account_boundary", f"Journey {journey_id} does not belong to {account_id}")
    return j


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    u, d = email.split("@", 1)
    return f"{u[:1]}***@{d}"


# -------------------------------------------------------------------- tools ---
def get_customer_context(ctx: ToolContext, a: CtxIn) -> CtxOut:
    db, aid = ctx.db, a.account_id
    acc = db.one("SELECT id,name,segment,goal,scenario,needs_directory FROM accounts WHERE id=?", (aid,))
    if not acc:
        raise ToolError("not_found", f"Unknown account {aid}")
    now = db.now()
    plans = {r["product"]: r["planned_start"] for r in db.q("SELECT product, planned_start FROM rollout_plans WHERE account_id=?", (aid,))}
    rollout = []
    for p, s in plans.items():
        rollout.append({"product": p, "planned_start": s, "started": from_iso(s) <= now})
    c = rules.admin_contact(db, aid)
    contact = None if not c else {"id": c["id"], "name": c["name"], "role": c["role"], "preferred_channel": c["preferred_channel"],
                                  "opted_out": bool(c["opted_out"]), "email": _mask(c["email"])}
    el = rules.evaluate_outreach(db, a.journey_id).to_dict() if a.journey_id and _journey(ctx, aid, a.journey_id) else None
    return CtxOut(account={k: acc[k] for k in ("id", "name", "segment", "goal")},
                  products=db.q("SELECT product, bundle, status FROM subscriptions WHERE account_id=?", (aid,)),
                  rollout=rollout,
                  journeys=db.q("SELECT id, product, state, paused_until FROM journeys WHERE account_id=?", (aid,)),
                  contact=contact, eligibility=el,
                  data_as_of=db.one("SELECT data_refreshed_at d FROM accounts WHERE id=?", (aid,))["d"], clock=to_iso(now))


def get_setup_progress(ctx: ToolContext, a: ProgIn) -> ProgOut:
    if not ctx.db.one("SELECT 1 x FROM subscriptions WHERE account_id=? AND product=?", (a.account_id, a.product)):
        raise ToolError("not_found", f"{a.account_id} has no {a.product} subscription")
    return ProgOut(**rules.progress(ctx.db, a.account_id, a.product))


def get_interaction_history(ctx: ToolContext, a: HistIn) -> HistOut:
    db = ctx.db
    sql = "SELECT * FROM interactions WHERE account_id=? AND kind='message'"
    params: list = [a.account_id]
    rows = db.q(sql + " ORDER BY rid DESC LIMIT ?", (*params, a.limit))[::-1]
    msgs = []
    for r in rows:
        sig = json.loads(r["signals"])
        msgs.append({"id": r["id"], "ts": r["ts"], "channel": r["channel"], "from": r["actor"], "body": r["body"][:600],
                     "message_kind": sig.get("message_kind"), "intent": sig.get("intent"), "doc_ids": sig.get("guidance_docs", []), "topic": sig.get("topic")})
    attempted: set[str] = set()
    guidance: list[str] = []
    for j in db.q("SELECT id, attempted_docs FROM journeys WHERE account_id=?" + (" AND id=?" if a.journey_id else ""),
                  (a.account_id, a.journey_id) if a.journey_id else (a.account_id,)):
        attempted |= set(json.loads(j["attempted_docs"]))
    for r in db.q("SELECT signals FROM interactions WHERE account_id=? AND actor='agent' AND kind='message' ORDER BY rid", (a.account_id,)):
        for d in json.loads(r["signals"]).get("guidance_docs", []):
            if d not in guidance:
                guidance.append(d)
    ts = db.one("SELECT COUNT(*) n FROM interactions WHERE account_id=? AND actor='agent' AND kind='message' "
                "AND json_extract(signals,'$.topic')='troubleshooting'" + (" AND journey_id=?" if a.journey_id else ""),
                (a.account_id, a.journey_id) if a.journey_id else (a.account_id,))["n"]
    lc = db.one("SELECT id FROM interactions WHERE account_id=? AND actor='customer' AND kind='message' ORDER BY rid DESC LIMIT 1", (a.account_id,))
    return HistOut(messages=msgs, attempted_doc_ids=sorted(attempted), guidance_doc_ids=guidance, troubleshooting_replies=ts,
                   last_customer_message_id=lc["id"] if lc else None)


def search_documentation(ctx: ToolContext, a: SearchIn) -> SearchOut:
    hits = get_retriever().search(a.query, a.top_k, a.product, set(a.exclude_doc_ids))
    supported = bool(hits) and hits[0]["score"] >= SUPPORT_THRESHOLD
    if ctx.retrieved is not None:
        known = get_retriever().doc_ids()
        for h in hits:
            ctx.retrieved.add(h["doc_id"])
            ctx.retrieved_sections.setdefault(h["doc_id"], set()).add(h["section"])
            ctx.retrieved |= {d for d in re.findall(r"DOC-\d{3}", h["excerpt"]) if d in known}
    note = ("Top result scored above the support threshold." if supported else
            "Documentation does not clearly cover this question. Do not answer from memory; explain the limit and offer a handoff.")
    return SearchOut(hits=hits if supported else hits[:1], supported=supported, note=note)


def check_support_cases(ctx: ToolContext, a: CasesIn) -> CasesOut:
    q, p = "SELECT id, product, subject, category, status, blocking, created_at FROM support_cases WHERE account_id=? AND status='open'", [a.account_id]
    t, tp = "SELECT id, journey_id, product, issue, priority, team, status, assignee FROM human_tasks WHERE account_id=? AND status!='resolved'", [a.account_id]
    if a.product:
        q += " AND product=?"; p.append(a.product)
        t += " AND product=?"; tp.append(a.product)
    cases, tasks = ctx.db.q(q, tuple(p)), ctx.db.q(t, tuple(tp))
    return CasesOut(open_cases=cases, open_tasks=tasks, blocking=any(c["blocking"] for c in cases) or bool(tasks))


def send_guidance(ctx: ToolContext, a: SendIn) -> SendOut:
    db = ctx.db
    j = _journey(ctx, a.account_id, a.journey_id)
    c = db.one("SELECT * FROM contacts WHERE id=?", (a.contact_id,))
    if not c:
        raise ToolError("not_found", f"Unknown contact {a.contact_id}")
    if c["account_id"] != a.account_id:
        raise ToolError("account_boundary", f"Contact {a.contact_id} does not belong to {a.account_id}")
    known = get_retriever().doc_ids()
    bad = [d for d in a.doc_ids if d not in known]
    if bad:
        raise ToolError("invalid_input", f"Unknown document IDs: {bad}")
    cited = set(re.findall(r"DOC-\d{3}", a.body))
    if cited - set(a.doc_ids):
        raise ToolError("invalid_citation", f"The message cites {sorted(cited - set(a.doc_ids))} but they are not listed as sources. Cite only documents you retrieved.")
    if ctx.retrieved is not None and set(a.doc_ids) - ctx.retrieved:
        raise ToolError("invalid_citation", f"{sorted(set(a.doc_ids) - ctx.retrieved)} were not retrieved in this run, so they cannot be cited.")
    if a.kind in ("proactive", "reply"):
        repeated = sorted(set(a.doc_ids) & set(json.loads(j["attempted_docs"])))
        if repeated:
            db.guard("repeat_guidance_prevented", a.account_id, a.journey_id, f"already tried: {repeated}")
            raise ToolError("repeat_guidance", f"Customer already tried {repeated}; do not repeat it.")
    el = rules.evaluate_outreach(db, a.journey_id, a.kind)
    if not el.allowed:
        db.guard("outreach_blocked", a.account_id, a.journey_id, f"{a.kind}: {','.join(el.codes())}")
        raise ToolError("policy_blocked", "Message not sent: " + "; ".join(b.message for b in el.blockers))
    titles = {c_.doc_id: c_.title for c_ in get_retriever().chunks}
    topic = "troubleshooting" if set(a.doc_ids) & {"DOC-105", "DOC-106"} else "guidance"
    body = (f"Subject: {a.subject}\n\n" if a.subject and a.channel == "email" else "") + a.body
    iid = db.timeline(a.account_id, "agent", "message", body, a.journey_id, a.contact_id, a.channel,
                      sources=[{"doc_id": d, "title": titles[d], "sections": sorted(ctx.retrieved_sections.get(d, []))} for d in a.doc_ids],
                      signals={"message_kind": a.kind, "guidance_docs": a.doc_ids, "topic": a.topic or (topic if a.doc_ids else "none")})
    nxt = None
    if a.kind != "confirmation":
        rules.set_journey_state(db, a.journey_id, "guidance_sent", f"{a.kind} message sent")
    if a.kind == "proactive":
        rules.cancel_pending(db, a.journey_id, "superseded by new reminder")
        due = db.now() + timedelta(days=db.get_settings().reminder_interval_days)
        rules.schedule(db, a.account_id, a.journey_id, "setup_reminder", due, "Follow up if milestone is still incomplete")
        nxt = to_iso(due)
    return SendOut(interaction_id=iid, channel=a.channel, delivery="simulated inbox", next_reminder_at=nxt)


def pause_journey(ctx: ToolContext, a: PauseIn) -> StateOut:
    db = ctx.db
    j = _journey(ctx, a.account_id, a.journey_id)
    if a.reason == "awaiting_human":
        target, until = "waiting_for_human", None
    else:
        target = "paused_until_rollout"
        if a.resume_on:
            try:
                until = from_iso(a.resume_on + "T09:00:00" if len(a.resume_on) == 10 else a.resume_on)
            except ValueError:
                raise ToolError("invalid_input", "resume_on must be YYYY-MM-DD")
        elif a.reason == "until_rollout":
            plan = db.one("SELECT planned_start FROM rollout_plans WHERE account_id=? AND product=?", (a.account_id, j["product"]))
            until = from_iso(plan["planned_start"]) if plan else db.now() + timedelta(days=30)
        else:
            until = db.now() + timedelta(days=30)
        if until <= db.now():
            raise ToolError("invalid_input", "resume_on must be in the future")
    ok, err = rules.set_journey_state(db, a.journey_id, target, f"paused: {a.reason}", paused_until=to_iso(until) if until else None)
    if not ok:
        raise ToolError("invalid_transition", err or "")
    rules.cancel_pending(db, a.journey_id, f"journey paused ({a.reason})", ("setup_reminder", "resume_check"))
    if until:
        rules.schedule(db, a.account_id, a.journey_id, "resume_check", until, f"Resume after pause: {a.reason}")
    return StateOut(journey_id=a.journey_id, state=target, detail=f"Reminders cancelled; resume check {to_iso(until) if until else 'after human resolution'}")


def resume_journey(ctx: ToolContext, a: ResumeIn) -> StateOut:
    db = ctx.db
    j = _journey(ctx, a.account_id, a.journey_id)
    if j["state"] not in ("paused_until_rollout", "resolved_awaiting_progress_check"):
        raise ToolError("invalid_transition", f"Cannot resume from {STATE_LABEL[j['state']]}")
    bl = rules.open_blockers(db, a.account_id, j["product"])
    if bl["tasks"]:
        raise ToolError("blocked", "A human task is still open for this product")
    ok, err = rules.set_journey_state(db, a.journey_id, "monitoring", f"resumed: {a.reason}", paused_until=None)
    if not ok:
        raise ToolError("invalid_transition", err or "")
    detail = "Journey is monitoring again"
    if not rules.progress(db, a.account_id, j["product"])["complete"]:
        due = db.now() + timedelta(days=db.get_settings().stall_threshold_days)
        rules.schedule(db, a.account_id, a.journey_id, "setup_reminder", due, "Check progress on next milestone")
        detail += f"; next progress reminder {to_iso(due)}"
    return StateOut(journey_id=a.journey_id, state="monitoring", detail=detail)


def create_handoff(ctx: ToolContext, a: HandoffIn) -> HandoffOut:
    db = ctx.db
    j = _journey(ctx, a.account_id, a.journey_id)
    existing = db.one("SELECT * FROM human_tasks WHERE account_id=? AND product=? AND status!='resolved' ORDER BY created_at LIMIT 1",
                      (a.account_id, j["product"]))
    if existing:
        db.guard("duplicate_prevented", a.account_id, a.journey_id, f"handoff already open: {existing['id']}")
        return HandoffOut(task_id=existing["id"], case_id=existing["case_id"], team=existing["team"], existing=True)
    case = db.one("SELECT * FROM support_cases WHERE account_id=? AND product=? AND status='open' AND blocking=1", (a.account_id, j["product"]))
    st = db.get_settings()
    team = st.team_for(a.category)
    case_id = case["id"] if case else db.next_id("CASE")
    if not case:
        db.insert("support_cases", id=case_id, account_id=a.account_id, product=j["product"], subject=a.issue, category=a.category,
                  status="open", blocking=1, created_at=to_iso(db.now()))
    msgs = db.q("SELECT id, actor, channel, ts, body, signals FROM interactions WHERE account_id=? AND kind='message' ORDER BY rid DESC LIMIT 8", (a.account_id,))[::-1]
    guidance = [{"id": m["id"], "ts": m["ts"], "channel": m["channel"], "excerpt": m["body"][:400],
                 "docs": json.loads(m["signals"]).get("guidance_docs", [])} for m in msgs if m["actor"] == "agent"]
    acc = db.one("SELECT name, goal FROM accounts WHERE id=?", (a.account_id,))
    attempted = sorted(set(a.attempted_doc_ids) | set(json.loads(j["attempted_docs"])))
    context = {"goal": acc["goal"], "account": acc["name"], "product": j["product"], "summary": a.summary,
               "progress": rules.progress(db, a.account_id, j["product"])["milestones"], "guidance_sent": guidance,
               "attempted_doc_ids": attempted,
               "conversation_refs": [{"id": m["id"], "from": m["actor"], "channel": m["channel"], "excerpt": m["body"][:160]} for m in msgs]}
    tid = db.next_id("TSK")
    db.insert("human_tasks", id=tid, account_id=a.account_id, journey_id=a.journey_id, product=j["product"], issue=a.issue,
              category=a.category, priority=a.priority, team=team, status="open", context=json.dumps(context),
              created_at=to_iso(db.now()), case_id=case_id)
    db.update("journeys", a.journey_id, attempted_docs=json.dumps(attempted))
    db.timeline(a.account_id, "system", "tool_action", f"Handoff {tid} created for {team} ({a.priority}): {a.issue}", a.journey_id)
    return HandoffOut(task_id=tid, case_id=case_id, team=team, existing=False)


def update_journey_status(ctx: ToolContext, a: StatusIn) -> StateOut:
    db = ctx.db
    j = _journey(ctx, a.account_id, a.journey_id)
    new = a.new_state
    if j["state"] == new:
        return StateOut(journey_id=a.journey_id, state=new, detail="Already in this state")
    if not can_transition(j["state"], new):
        raise ToolError("invalid_transition", f"{STATE_LABEL[j['state']]} -> {STATE_LABEL[new]} is not allowed")
    if new == "completed":
        pr = rules.progress(db, a.account_id, j["product"])
        if not pr["complete"]:
            raise ToolError("completion_not_supported", "Setup progress does not show all milestones complete")
        rules.set_journey_state(db, a.journey_id, "completed", a.reason, paused_until=None)
        n = rules.cancel_pending(db, a.journey_id, "setup complete", ("setup_reminder", "resume_check"))
        return StateOut(journey_id=a.journey_id, state=new, detail=f"Completed; {n} pending reminder(s) cancelled")
    if new == "opted_out":
        rules.apply_opt_out(db, a.account_id)
        return StateOut(journey_id=a.journey_id, state=new, detail="All journeys for this account stopped; no further messages")
    ok, err = rules.set_journey_state(db, a.journey_id, new, a.reason)
    if not ok:
        raise ToolError("invalid_transition", err or "")
    return StateOut(journey_id=a.journey_id, state=new, detail="State updated")


# ------------------------------------------------------ Account Team tools ---
class MeetingIn(In):
    meeting_id: str


class MeetingOut(BaseModel):
    meeting: dict
    account: dict
    days_until: float
    cancelled: bool
    changed: bool
    past: bool


class LearnIn(In):
    product: Product


class LearnOut(BaseModel):
    has_records: bool
    learner_count: int
    courses: dict
    learners: list[dict]
    records_updated_at: str | None
    stale: bool
    note: str


class CatalogIn(In):
    query: str = Field(min_length=3, max_length=300)
    product: Product | None = None
    top_k: int = Field(4, ge=1, le=8)


class CatalogOut(BaseModel):
    courses: list[dict]


class BlockersIn(In):
    meeting_id: str | None = None


class BlockersOut(BaseModel):
    open_cases: list[dict]
    open_tasks: list[dict]
    blocking: bool
    rollouts: list[dict]
    rollout_not_started: bool
    recommendations: list[dict]


class SaveRecIn(MutIn):
    meeting_id: str
    action_type: Literal["training", "technical_followup", "timing", "clarify", "discovery", "no_action"]
    title: str = Field(min_length=8, max_length=200)
    why_now: str = Field(min_length=10, max_length=700)
    talking_point: str = Field(min_length=10, max_length=700)
    brief: str = Field(min_length=20, max_length=1500)
    course_ids: list[str] = []
    learner_summary: str = Field("", max_length=400)
    unknowns: list[str] = []
    evidence_refs: list[str] = []
    free_alternatives_considered: str | None = Field(None, max_length=400)


class SaveRecOut(BaseModel):
    rec_id: str
    status: str
    existing: bool
    superseded: str | None = None


class FeedbackIn(In):
    rec_id: str
    action: Literal["reviewed", "accepted", "edited", "dismissed", "deferred", "discussed"]
    reviewer: str
    reason: str | None = None
    note: str | None = Field(None, max_length=500)
    revised: dict | None = None
    defer_until: str | None = None
    idempotency_key: str | None = None


class FeedbackOut(BaseModel):
    rec_id: str
    status: str


REC_TRANSITIONS = {
    "generated": {"reviewed", "accepted", "edited", "dismissed", "deferred"},
    "reviewed": {"accepted", "edited", "dismissed", "deferred"},
    "accepted": {"discussed", "dismissed", "edited"},
    "edited": {"discussed", "dismissed", "accepted"},
    "deferred": {"reviewed", "accepted", "edited", "dismissed"},
    "discussed": set(), "dismissed": set(), "withdrawn": set(),
}
ACTIVE_REC = ("generated", "reviewed", "accepted", "edited", "discussed")
EXPECTED_EVIDENCE = {"meeting": "Meeting purpose and date", "account_goal": "Customer goal", "product_usage": "Usage and milestone progress",
                     "learning_records": "Learning progress", "support_and_rollout": "Support cases and rollout plan", "training_catalog": "Training catalog"}


def _meeting(ctx: ToolContext, account_id: str, meeting_id: str) -> dict:
    m = ctx.db.one("SELECT * FROM meetings WHERE id=?", (meeting_id,))
    if not m:
        raise ToolError("not_found", f"Unknown meeting {meeting_id}")
    if m["account_id"] != account_id:
        raise ToolError("account_boundary", f"Meeting {meeting_id} does not belong to {account_id}")
    return m


def get_meeting_context(ctx: ToolContext, a: MeetingIn) -> MeetingOut:
    db = ctx.db
    m = _meeting(ctx, a.account_id, a.meeting_id)
    acc = db.one("SELECT id, name, goal, lifecycle, owner, solutions_architect FROM accounts WHERE id=?", (a.account_id,))
    days = (from_iso(m["starts_at"]) - db.now()).total_seconds() / 86400
    m = {**m, "attendee_roles": json.loads(m["attendee_roles"])}
    return MeetingOut(meeting=m, account=acc, days_until=round(days, 2), cancelled=m["status"] == "cancelled", changed=bool(m["previous_start"]),
                      past=days < 0 or m["status"] == "completed")


def get_learning_progress(ctx: ToolContext, a: LearnIn) -> LearnOut:
    db = ctx.db
    courses = [c["id"] for c in db.q("SELECT id FROM courses WHERE product=?", (a.product,))]
    ph = ",".join("?" * len(courses))
    rows = db.q(f"SELECT * FROM learner_records WHERE account_id=? AND course_id IN ({ph}) ORDER BY learner_id", (a.account_id, *courses)) if courses else []
    if not rows:
        return LearnOut(has_records=False, learner_count=0, courses={}, learners=[], records_updated_at=None, stale=False,
                        note="No learner records on file. Do not assume anyone has or has not been trained.")
    per: dict[str, dict] = {}
    learners: dict[str, dict] = {}
    for r in rows:
        c = per.setdefault(r["course_id"], {"completed": 0, "started": 0, "enrolled": 0})
        if r["status"] in c:
            c[r["status"]] += 1
        l = learners.setdefault(r["learner_id"], {"learner_id": r["learner_id"], "role": r["role"], "courses": {}})
        l["courses"][r["course_id"]] = r["status"]
    updated = max(r["record_updated_at"] for r in rows)
    stale = db.now() - from_iso(updated) > timedelta(days=db.get_settings().stale_data_days)
    return LearnOut(has_records=True, learner_count=len(learners), courses=per, learners=list(learners.values()), records_updated_at=updated, stale=stale,
                    note="Learner records are older than the freshness limit; confirm with the customer." if stale else "Learner records are current.")


def search_training_catalog(ctx: ToolContext, a: CatalogIn) -> CatalogOut:
    from .retrieval import tokenize
    q = set(tokenize(a.query))
    out = []
    for c in ctx.db.q("SELECT * FROM courses" + (" WHERE product=?" if a.product else ""), (a.product,) if a.product else ()):
        text = " ".join([c["title"], c["topic"], c["persona"], " ".join(json.loads(c["skills"]))])
        score = len(q & set(tokenize(text))) / (len(q) or 1)
        if score > 0:
            out.append((score, {**c, "prerequisites": json.loads(c["prerequisites"]), "skills": json.loads(c["skills"]), "paid": bool(c["paid"]), "match": round(score, 2)}))
    out.sort(key=lambda x: (-x[0], x[1]["id"]))
    return CatalogOut(courses=[c for _, c in out[: a.top_k]])


def get_account_blockers(ctx: ToolContext, a: BlockersIn) -> BlockersOut:
    db = ctx.db
    cases = db.q("SELECT id, product, subject, category, blocking, created_at FROM support_cases WHERE account_id=? AND status='open'", (a.account_id,))
    tasks = db.q("SELECT id, product, issue, priority, status FROM human_tasks WHERE account_id=? AND status!='resolved'", (a.account_id,))
    now = db.now()
    rollouts = [{"product": r["product"], "planned_start": r["planned_start"], "started": from_iso(r["planned_start"]) <= now}
                for r in db.q("SELECT product, planned_start FROM rollout_plans WHERE account_id=?", (a.account_id,))]
    recs = db.q("SELECT id, meeting_id, status, action_type, dedupe_key, title, defer_until FROM recommendations WHERE account_id=?", (a.account_id,))
    for r in recs:
        fb = db.one("SELECT reason FROM rec_feedback WHERE rec_id=? AND action IN ('dismissed','deferred') ORDER BY id DESC LIMIT 1", (r["id"],))
        r["reason"] = fb["reason"] if fb else None
    return BlockersOut(open_cases=cases, open_tasks=tasks, blocking=any(c["blocking"] for c in cases) or bool(tasks), rollouts=rollouts,
                       rollout_not_started=any(not r["started"] for r in rollouts), recommendations=recs)


def _group_for(ctx: ToolContext, account_id: str, course_id: str) -> tuple[list[str], list[str]]:
    """(learners who still need the course and meet its prerequisites, learners blocked by prerequisites)."""
    db = ctx.db
    prereqs = json.loads(db.one("SELECT prerequisites p FROM courses WHERE id=?", (course_id,))["p"])
    done: dict[str, set[str]] = {}
    for r in db.q("SELECT learner_id, course_id, status FROM learner_records WHERE account_id=?", (account_id,)):
        if r["status"] == "completed":
            done.setdefault(r["learner_id"], set()).add(r["course_id"])
    all_l = {r["learner_id"] for r in db.q("SELECT DISTINCT learner_id FROM learner_records WHERE account_id=?", (account_id,))}
    need = [l for l in all_l if course_id not in done.get(l, set())]
    ready = [l for l in need if set(prereqs) <= done.get(l, set())]
    return sorted(ready), sorted(set(need) - set(ready))


def save_recommendation(ctx: ToolContext, a: SaveRecIn) -> SaveRecOut:
    db = ctx.db
    m = _meeting(ctx, a.account_id, a.meeting_id)
    if m["status"] != "scheduled":
        raise ToolError("meeting_not_active", f"Meeting {a.meeting_id} is {m['status']}; no recommendation is created for it.")
    if from_iso(m["starts_at"]) < db.now():
        raise ToolError("meeting_not_active", "The meeting is in the past.")
    missing = [e for e in a.evidence_refs if e not in ctx.evidence]
    if missing:
        raise ToolError("unsupported_evidence", f"Evidence {missing} was not gathered in this run. Only cite evidence returned by tools.")
    if a.action_type != "clarify" and not a.evidence_refs:
        raise ToolError("unsupported_evidence", "A recommendation must cite at least one piece of gathered evidence.")
    sources = {ctx.evidence[e]["source"] for e in a.evidence_refs}
    courses = []
    if a.action_type == "training":
        if not a.course_ids:
            raise ToolError("invalid_input", "A training recommendation needs at least one course.")
        if not ({"learning_records"} <= sources and "training_catalog" in sources):
            raise ToolError("unsupported_evidence", "A training recommendation must cite learner records and the training catalog.")
        for cid in a.course_ids:
            c = db.one("SELECT * FROM courses WHERE id=?", (cid,))
            if not c:
                raise ToolError("invalid_input", f"Unknown course {cid}")
            ready, blocked = _group_for(ctx, a.account_id, cid)
            if not ready and not blocked:
                raise ToolError("already_completed", f"Everyone on record has already completed {cid}.")
            if not ready and blocked:
                raise ToolError("prerequisite_unmet", f"No learner meets the prerequisites for {cid} ({json.loads(c['prerequisites'])}). Recommend the prerequisite first.")
            if c["paid"] and not a.free_alternatives_considered:
                raise ToolError("paid_needs_justification", f"{cid} is paid. State which free alternatives were considered and why they are not enough.")
            courses.append({"course_id": cid, "title": c["title"], "paid": bool(c["paid"]), "price_note": c["price_note"], "format": c["format"], "duration_min": c["duration_min"],
                            "prerequisites": json.loads(c["prerequisites"]), "learners_ready": len(ready), "learners_blocked": len(blocked), "availability": c["availability"],
                            "source_doc": c["source_doc"], "source_section": c["source_section"], "free_alternatives_considered": a.free_alternatives_considered})
    dedupe = f"{a.account_id}|{a.meeting_id}|{a.action_type}|{','.join(sorted(a.course_ids))}"
    prior = db.q("SELECT * FROM recommendations WHERE dedupe_key=? ORDER BY created_at DESC, id DESC", (dedupe,))
    superseded = None
    for r in prior:
        fb = db.one("SELECT reason FROM rec_feedback WHERE rec_id=? AND action IN ('dismissed','deferred') ORDER BY id DESC LIMIT 1", (r["id"],))
        if r["status"] == "dismissed":
            db.guard("duplicate_prevented", a.account_id, None, f"dismissed recommendation {r['id']} not re-created")
            raise ToolError("previously_dismissed", f"{r['id']} was dismissed ({(fb or {}).get('reason') or 'no reason recorded'}); not recommending it again.")
        if r["status"] == "deferred":
            raise ToolError("deferred_recommendation", f"{r['id']} was deferred ({(fb or {}).get('reason') or 'no reason recorded'}); leave it deferred.")
        if r["status"] in ACTIVE_REC and not r["needs_refresh"]:
            db.guard("duplicate_prevented", a.account_id, None, f"recommendation {r['id']} already exists")
            return SaveRecOut(rec_id=r["id"], status=r["status"], existing=True)
        if r["status"] in ACTIVE_REC and r["needs_refresh"]:
            db.update("recommendations", r["id"], status="withdrawn", updated_at=to_iso(db.now()))
            superseded = r["id"]
    acc = db.one("SELECT goal FROM accounts WHERE id=?", (a.account_id,))
    evidence = [{**ctx.evidence[e], "id": e} for e in a.evidence_refs]
    have = {ev["source"] for ev in ctx.evidence.values()}
    completeness = {"have": [EXPECTED_EVIDENCE[k] for k in EXPECTED_EVIDENCE if k in have], "missing": [EXPECTED_EVIDENCE[k] for k in EXPECTED_EVIDENCE if k not in have]}
    rid = db.next_id("REC")
    content = {"title": a.title, "why_now": a.why_now, "talking_point": a.talking_point, "brief": a.brief, "unknowns": a.unknowns}
    now = to_iso(db.now())
    db.insert("recommendations", id=rid, account_id=a.account_id, meeting_id=a.meeting_id, status="generated", action_type=a.action_type, title=a.title,
              why_now=a.why_now, goal=acc["goal"] or "", talking_point=a.talking_point, brief=a.brief, evidence=json.dumps(evidence),
              learner_group=json.dumps({"summary": a.learner_summary}), courses=json.dumps(courses), unknowns=json.dumps(a.unknowns),
              completeness=json.dumps(completeness), generation_mode=ctx.mode, agent_version="meeting-prep-v1", dedupe_key=dedupe, needs_refresh=0,
              content_original=json.dumps(content), content_current=json.dumps(content), created_at=now, updated_at=now)
    db.timeline(a.account_id, "system", "tool_action", f"Recommendation {rid} generated for meeting {a.meeting_id}: {a.title}")
    db.insert("meeting_events", meeting_id=a.meeting_id, event="brief_generated", reviewer="system", ts=now)
    return SaveRecOut(rec_id=rid, status="generated", existing=False, superseded=superseded)


def record_recommendation_feedback(ctx: ToolContext, a: FeedbackIn) -> FeedbackOut:
    db = ctx.db
    if ctx.actor != "human":
        raise ToolError("not_permitted", "Only a human reviewer can review recommendations.")
    r = db.one("SELECT * FROM recommendations WHERE id=?", (a.rec_id,))
    if not r:
        raise ToolError("not_found", f"Unknown recommendation {a.rec_id}")
    if r["account_id"] != a.account_id:
        raise ToolError("account_boundary", f"{a.rec_id} does not belong to {a.account_id}")
    if a.reviewer not in REVIEWERS:
        raise ToolError("invalid_input", "Reviewer must be one of the synthetic reviewer identities.")
    if a.action not in REC_TRANSITIONS[r["status"]]:
        raise ToolError("invalid_transition", f"{r['status']} -> {a.action} is not allowed")
    if a.action in ("dismissed", "deferred") and a.reason not in DISMISS_REASONS:
        raise ToolError("invalid_input", f"A reason is required: {DISMISS_REASONS}")
    now = to_iso(db.now())
    original = json.loads(r["content_original"])
    revised = None
    vals: dict = {"status": a.action, "updated_at": now}
    if a.action == "edited":
        if not a.revised:
            raise ToolError("invalid_input", "Provide the revised content.")
        cur = json.loads(r["content_current"])
        revised = {**cur, **{k: v for k, v in a.revised.items() if k in ("title", "why_now", "talking_point", "brief") and str(v).strip()}}
        vals.update(content_current=json.dumps(revised), title=revised["title"], why_now=revised["why_now"], talking_point=revised["talking_point"], brief=revised["brief"])
    if a.action == "deferred":
        vals["defer_until"] = a.defer_until
    db.update("recommendations", a.rec_id, **vals)
    db.insert("rec_feedback", rec_id=a.rec_id, account_id=a.account_id, meeting_id=r["meeting_id"], reviewer=a.reviewer, action=a.action, reason=a.reason,
              note=a.note, original=json.dumps(original), revised=json.dumps(revised) if revised else None, ts=now)
    db.timeline(a.account_id, "human", "human_update", f"{a.reviewer} marked recommendation {a.rec_id} as {a.action}" + (f" ({a.reason})" if a.reason else ""))
    return FeedbackOut(rec_id=a.rec_id, status=a.action)


def build_evidence(ctx: ToolContext, name: str, args, out) -> list[dict]:
    """Evidence items the caller may cite. Each carries a source label and a timestamp."""
    items: list[tuple[str, str, str | None]] = []
    now = to_iso(ctx.db.now())
    if name == "get_meeting_context":
        m, acc = out.meeting, out.account
        items = [(f"Meeting {m['id']}: {m['purpose']} on {m['starts_at'][:10]}", "meeting", now), (f"Customer goal: {acc['goal']}", "account_goal", now)]
    elif name == "get_customer_context" and out.account.get("goal") and getattr(args, "journey_id", None) is None:
        items = [(f"Customer goal: {out.account['goal']}", "account_goal", out.data_as_of)]
    elif name == "get_setup_progress":
        items = [(f"{out.done_count} of {out.total} {out.product} milestones done; shared-workflow events {out.workflow_recent} in the last 14 days vs {out.workflow_prior} in the 30 days before; "
                  f"usage sessions {out.usage_recent} vs {out.usage_prior}", "product_usage", out.data_as_of)]
    elif name == "get_learning_progress":
        items = [(out.note + (f" {out.learner_count} learners on record." if out.has_records else ""), "learning_records", out.records_updated_at)]
    elif name == "get_account_blockers":
        items = [(f"{len(out.open_cases)} open case(s), {len(out.open_tasks)} open task(s); rollout started: {('yes' if all(r['started'] for r in out.rollouts) else 'not yet') if out.rollouts else 'no plan on file'}",
                  "support_and_rollout", now)]
    elif name == "check_support_cases":
        items = [(f"{len(out.open_cases)} open case(s), {len(out.open_tasks)} open task(s)", "support_and_rollout", now)]
    elif name == "search_training_catalog":
        items = [(f"Catalog match: {', '.join(c['id'] for c in out.courses) or 'none'}", "training_catalog", now)]
    res = []
    for label, source, ts in items:
        eid = f"E{len(ctx.evidence) + 1}"
        ctx.evidence[eid] = {"label": label, "source": source, "ts": ts}
        res.append({"id": eid, "label": label, "source": source, "ts": ts})
    return res


# ----------------------------------------------------------------- registry ---
@dataclass
class ToolSpec:
    name: str
    description: str
    input: type[BaseModel]
    output: type[BaseModel]
    fn: Callable
    mutating: bool = False


TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("get_customer_context", "Get the account goal, purchased products, rollout plan, journeys, contact preferences and whether outreach is currently allowed (with reasons).", CtxIn, CtxOut, get_customer_context),
    ToolSpec("get_setup_progress", "Get fresh onboarding milestone progress for one product, including the next incomplete milestone and data freshness.", ProgIn, ProgOut, get_setup_progress),
    ToolSpec("get_interaction_history", "Get recent messages across email and chat, guidance already sent, and steps the customer already tried.", HistIn, HistOut, get_interaction_history),
    ToolSpec("search_documentation", "Search the product knowledge base. Returns excerpts with document IDs and whether the docs actually support the question.", SearchIn, SearchOut, search_documentation),
    ToolSpec("check_support_cases", "List open support cases and open human tasks for the account.", CasesIn, CasesOut, check_support_cases),
    ToolSpec("send_guidance", "Send a message to the customer's admin contact. Policy rules may refuse it; read the result. kind=proactive for agent-initiated, reply for answering a customer message, status_update for case updates, confirmation for acknowledging an opt-out.", SendIn, SendOut, send_guidance, True),
    ToolSpec("pause_journey", "Pause automated outreach. reason=awaiting_human while a person works the case; until_rollout or customer_request with resume_on date.", PauseIn, StateOut, pause_journey, True),
    ToolSpec("resume_journey", "Resume a paused journey or one whose human task was resolved. Only valid from paused_until_rollout or resolved_awaiting_progress_check.", ResumeIn, StateOut, resume_journey, True),
    ToolSpec("create_handoff", "Create a task for a human team (never duplicates an open one). Include what was tried.", HandoffIn, HandoffOut, create_handoff, True),
    ToolSpec("get_meeting_context", "Get an upcoming meeting: purpose, date, owner, attendees, whether it was changed or cancelled, and the account lifecycle stage.", MeetingIn, MeetingOut, get_meeting_context),
    ToolSpec("get_learning_progress", "Get learner records for the account: who completed which course, how fresh the records are, and whether data is missing.", LearnIn, LearnOut, get_learning_progress),
    ToolSpec("search_training_catalog", "Search the fictional training catalog. Returns courses with prerequisites, format, duration and whether they are free or paid.", CatalogIn, CatalogOut, search_training_catalog),
    ToolSpec("get_account_blockers", "Get open technical cases/tasks, rollout status, and earlier recommendations (including dismissed and deferred ones) for the account.", BlockersIn, BlockersOut, get_account_blockers),
    ToolSpec("save_recommendation", "Save a recommendation for human review. Cite only evidence IDs returned by tools. Training recommendations need learner-record and catalog evidence, valid prerequisites, and a justification for paid options. Nothing is sent to the customer.", SaveRecIn, SaveRecOut, save_recommendation, True),
    ToolSpec("record_recommendation_feedback", "Human reviewers only: record review, acceptance, edit, dismissal, deferral or discussion.", FeedbackIn, FeedbackOut, record_recommendation_feedback, True),
    ToolSpec("update_journey_status", "Move the journey state. completed requires fresh progress showing all milestones done; opted_out stops all messages.", StatusIn, StateOut, update_journey_status, True),
]}


def tool_schemas(allowed: set[str] | None = None) -> list[dict]:
    out = []
    for t in TOOLS.values():
        if allowed is not None and t.name not in allowed:
            continue
        schema = t.input.model_json_schema()
        schema.get("properties", {}).pop("idempotency_key", None)
        schema.pop("title", None)
        out.append({"name": t.name, "description": t.description, "input_schema": schema})
    return out


def _fail(code: str, msg: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}, "deduplicated": False}


def execute_tool(ctx: ToolContext, name: str, raw_args: dict, rationale: str = "", idempotency_key: str | None = None) -> dict:
    """Validate, authorise, deduplicate, run and record one tool call."""
    db = ctx.db
    args_for_log = dict(raw_args or {})
    result: dict
    spec = TOOLS.get(name)
    if not spec:
        result = _fail("unknown_tool", f"No tool named {name}")
    else:
        if spec.mutating and idempotency_key:
            args_for_log["idempotency_key"] = idempotency_key
        try:
            args = spec.input(**args_for_log)
        except ValidationError as e:
            result = _fail("invalid_input", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
        else:
            if ctx.allowed is not None and name not in ctx.allowed:
                result = _fail("tool_not_permitted", f"{name} is not permitted in this workflow")
            elif args.account_id != ctx.account_id:
                db.guard("boundary_violation", ctx.account_id, None, f"{name} called with account {args.account_id}")
                result = _fail("account_boundary", f"This run may only access {ctx.account_id}")
            else:
                key = getattr(args, "idempotency_key", None)
                prior = db.one("SELECT result FROM idempotency WHERE key=?", (key,)) if key else None
                if prior:
                    db.guard("duplicate_prevented", ctx.account_id, None, f"{name} repeated with key {key}")
                    result = {**json.loads(prior["result"]), "deduplicated": True}
                else:
                    try:
                        if name == "create_handoff" and db.get_settings().fault_create_handoff:
                            raise ToolError("tool_unavailable", "Handoff service is unavailable (simulated failure)")
                        out = spec.fn(ctx, args)
                        result = {"ok": True, "data": out.model_dump(), "error": None, "deduplicated": False}
                        ev = build_evidence(ctx, name, args, out)
                        if ev:
                            result["data"]["evidence"] = ev
                        if key:
                            db.x("INSERT OR REPLACE INTO idempotency(key,tool,result,created_at) VALUES(?,?,?,?)",
                                 (key, name, json.dumps(result, default=str), to_iso(db.now())))
                    except ToolError as e:
                        result = _fail(e.code, e.message)
                    except Exception as e:  # unexpected bug: still explicit, never silent
                        result = _fail("internal_error", f"{type(e).__name__}: {e}")
    if not result["ok"]:
        db.guard("tool_error", ctx.account_id, None, f"{name}: {result['error']['code']}")
    db.insert("tool_executions", id=db.next_id("EXE", 4), run_id=ctx.run_id, account_id=ctx.account_id, tool=name,
              args=json.dumps(args_for_log, default=str), result=json.dumps(result, default=str)[:6000], ok=int(result["ok"]),
              error=(result["error"] or {}).get("code") if result["error"] else None, rationale=rationale,
              deduplicated=int(result["deduplicated"]), ts=to_iso(db.now()))
    return result
