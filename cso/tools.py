"""Agent tools: validated inputs/outputs, account-boundary enforcement and real state changes.

Every tool returns a ToolResult dict. A failure is always explicit (ok=False with an error code),
so callers (scripted or live) cannot claim an action succeeded when it did not.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass
class ToolContext:
    db: DB
    run_id: str | None
    account_id: str  # the single account this run may touch


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
                     "message_kind": sig.get("message_kind"), "intent": sig.get("intent"), "doc_ids": sig.get("guidance_docs", [])})
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
                      sources=[{"doc_id": d, "title": titles[d]} for d in a.doc_ids],
                      signals={"message_kind": a.kind, "guidance_docs": a.doc_ids, "topic": topic if a.doc_ids else "none"})
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
    guidance = [{"id": m["id"], "ts": m["ts"], "channel": m["channel"], "excerpt": m["body"][:240],
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
    ToolSpec("update_journey_status", "Move the journey state. completed requires fresh progress showing all milestones done; opted_out stops all messages.", StatusIn, StateOut, update_journey_status, True),
]}


def tool_schemas() -> list[dict]:
    out = []
    for t in TOOLS.values():
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
            if args.account_id != ctx.account_id:
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
