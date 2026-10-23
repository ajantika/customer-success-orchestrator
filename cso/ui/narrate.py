"""Plain-language explanation of what an agent run found, did and why. Technical details stay in expanders."""
from __future__ import annotations

import json
import re

from ..format import when

MUTATING = {"send_guidance", "pause_journey", "resume_journey", "create_handoff", "update_journey_status", "save_recommendation"}


PLAIN = {
    "frequency": "a message was sent recently, so the assistant waits (limits: 2 per week, at least 48 hours apart)",
    "stalled": "setup has not been quiet for long enough yet",
    "rollout_started": "the customer's planned rollout has not started",
    "no_blocking_case": "a support issue or a person is already working on this",
    "opt_out": "the customer asked not to be contacted",
    "missing_data": "essential customer information is missing",
    "stale_data": "the product data is out of date",
    "unanswered_cap": "earlier messages have gone unanswered",
    "setup_incomplete": "setup is already complete",
    "journey_open": "this journey is already finished",
}


def plain_blockers(checks: list[dict]) -> str:
    return "; ".join(PLAIN.get(c["code"], c["message"]) for c in checks if not c["passed"])


def evidence_lines(parsed: list[tuple[dict, dict]]) -> list[str]:
    ev = []
    for e, r in parsed:
        d = r.get("data") or {}
        t = e["tool"]
        if not r["ok"] and t in MUTATING:
            ev.append(f"The action “{t.replace('_', ' ')}” was not done: {r['error']['message']}")
        if t == "get_setup_progress" and d:
            nm = d["next_milestone"]["customer_label"] if d["next_milestone"] else "none"
            ev.append(f"Setup progress: {d['done_count']} of {d['total']} steps done. Next step: {nm}.")
        elif t == "get_customer_context" and d and d.get("eligibility"):
            ev.append("At the time of the check, the customer could be contacted." if d["eligibility"]["allowed"] else "The customer should not be contacted yet: " + plain_blockers(d["eligibility"]["checks"]) + ".")
        elif t == "search_documentation" and d:
            ev.append("Help articles found: " + ", ".join(f"{h['title']} › {h['section']}" for h in d["hits"]) + ("" if d["supported"] else " (not a good match)") + ".")
        elif t == "check_support_cases" and d:
            ev.append(f"Open support cases: {len(d['open_cases'])}; open tasks for people: {len(d['open_tasks'])}.")
        elif t == "get_interaction_history" and d:
            ev.append(f"Read {len(d['messages'])} earlier message(s). Documents the customer already tried: {', '.join(d['attempted_doc_ids']) or 'none'}.")
        elif t == "get_meeting_context" and d:
            m = d["meeting"]
            ev.append(f"Meeting {when(m['starts_at'])}: {m['purpose']}." + (" The meeting is cancelled." if d["cancelled"] else ""))
        elif t == "get_learning_progress" and d:
            ev.append(f"{d['learner_count']} learner(s) on record." if d["has_records"] else "No learner records on file.")
            if d["has_records"] and d["stale"]:
                ev.append(f"Learner records are out of date (last updated {when(d['records_updated_at'], False)}).")
        elif t == "get_account_blockers" and d:
            ev.append(f"Open technical items: {len(d['open_cases']) + len(d['open_tasks'])}. Rollout not started: {'yes' if d['rollout_not_started'] else 'no'}.")
        elif t == "search_training_catalog" and d:
            ev.append("Training options considered: " + (", ".join(c["title"] for c in d["courses"][:3]) or "none") + ".")
    return ev


def headline(summary: str, trigger: str, tone: str) -> str:
    """A one-sentence result in plain words. The full summary stays in the details section."""
    t = summary
    rules = [
        (r"^Sent guidance for", "The assistant sent setup guidance to the customer."),
        (r"asked a clarifying question", "The assistant asked which error occurred."),
        (r"^Sent guidance grounded in", "The assistant sent the matching troubleshooting steps."),
        (r"^Created TSK-\d+", "A support task was created and reminders were paused."),
        (r"^Handoff FAILED", "The support task could not be created, so the customer was told nothing was created."),
        (r"already exists; duplicate", "A support task already exists, so no duplicate was created."),
        (r"Open support request .* exists", "A support request is already open, so only a status reply was sent."),
        (r"^Support task resolved, but onboarding is not complete", "The assistant checked setup and updated the customer. Onboarding is not complete yet."),
        (r"^Verified completion", "The assistant confirmed setup is complete and stopped the reminders."),
        (r"^Fresh progress check: all milestones complete", "The assistant confirmed setup is complete and stopped the reminders."),
        (r"Customer said setup is complete but product events disagree", "The assistant did not see the setup steps finished, so the journey stays open."),
        (r"^Customer opted out", "The assistant stopped all messages, as the customer asked."),
        (r"rollout is later; journey paused", "The assistant paused messages until the customer's rollout date."),
        (r"^Rejected a message that tried to override", "The assistant declined that request."),
        (r"^Documentation did not support", "The assistant said it could not find an answer and offered to involve a person."),
        (r"^Sent getting-started guidance", "The assistant sent getting-started guidance."),
        (r"^No outreach", "No message was sent: the rules say to wait."),
        (r"^Holding:", "No message was sent: support is already working on this."),
        (r"^Saved recommendation", "A suggested next step was prepared for review. Nothing was sent to the customer."),
        (r"already exists for this meeting", "The suggested next step already exists, so nothing was duplicated."),
        (r"^The meeting is cancelled", "The meeting is cancelled, so no suggestion was prepared."),
    ]
    for pat, msg in rules:
        if re.search(pat, t):
            return msg
    return t if len(t) < 140 else t[:137] + "…"


def from_run(db, run_id: str) -> dict:
    run = db.one("SELECT * FROM agent_runs WHERE id=?", (run_id,))
    ex = db.q("SELECT * FROM tool_executions WHERE run_id=? ORDER BY rid", (run_id,))
    parsed = [(e, json.loads(e["result"])) for e in ex]
    found = evidence_lines(parsed)
    if run["trigger"] in ("customer_reply", "progress_check"):
        # replying to a customer who wrote to us is allowed even when proactive outreach is limited
        found = [f for f in found if not f.startswith(("The customer should not", "At the time of the check"))]
        msg = db.one("SELECT body, signals FROM interactions WHERE id=?", (run["trigger_ref"].replace("reply:", ""),)) if run["trigger"] == "customer_reply" else None
        if msg:
            intent = json.loads(msg["signals"]).get("intent", "unknown").replace("_", " ")
            found.insert(0, f"The customer wrote: “{msg['body'][:110]}” (understood as: {intent}).")
    why = ""
    for tool in ("create_handoff", "send_guidance", "pause_journey", "save_recommendation", "resume_journey", "update_journey_status"):
        hit = next((e["rationale"] for e, r in parsed if e["tool"] == tool and r["ok"] and e["rationale"]), "")
        if hit:
            why = hit
            break
    if run["trigger"] == "meeting_prep":
        rec = next((r["data"] for e, r in parsed if e["tool"] == "save_recommendation" and r["ok"]), None)
        if rec:
            row = db.one("SELECT why_now FROM recommendations WHERE id=?", (rec["rec_id"],))
            why = row["why_now"] if row else why
    if not why:
        last = next((e["rationale"] for e, r in reversed(parsed) if e["rationale"]), "")
        why = last or "The rules did not allow or require any action."
    tone = "error" if run["outcome"] == "error" else "warning" if run["outcome"] == "step_limit" else "success"
    full = run["summary"] + (f" Error: {run['error']}" if run["error"] else "")
    return {"found": found[:4], "did": full, "short": headline(run["summary"], run["trigger"], tone), "why": why, "tone": tone, "run_id": run_id}
