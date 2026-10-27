"""Deterministic synthetic data. Everything here is fictional and labelled synthetic (origin='seed')."""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta

from .db import DB, to_iso
from .models import PRODUCTS, DEFAULT_MILESTONES, Settings

SEED = 7
FEATURED = "ACC-001"
from .seed_team import NORTHSTAR, seed_catalog, seed_northstar, seed_team_history

NAMES = [
    "Harbor Logistics", "Juniper Health", "Northwind Studio", "Copperline Finance", "Alder & Pine", "Brightpath Learning",
    "Cedar Ridge Homes", "Driftwood Media", "Eastgate Foods", "Fieldstone Labs", "Granite Peak Energy", "Hollow Oak Games",
    "Ironbridge Systems", "Kestrel Aviation", "Lumen Analytics", "Meridian Travel", "Nimbus Robotics", "Orchard Retail",
    "Pinecone Pediatrics", "Quarry Works", "Riverbend Bank", "Saltmarsh Marine", "Tidewater Legal", "Upland Farms",
    "Violet Hour Events", "Willow Creek Dental", "Yarrow Biotech", "Zephyr Outdoors", "Anchor Point Realty", "Birchwood Print",
    "Cobalt Mining Co", "Dovetail Furniture", "Evergreen Schools", "Foxglove Pharmacy", "Gable & Finch", "Heron Telecom",
    "Indigo Architects", "Jasper Coffee Group", "Lantern Nonprofit",
]
FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn", "Drew", "Reese"]
LAST = ["Reyes", "Patel", "Nguyen", "Okafor", "Lindqvist", "Moreau", "Santos", "Kowalski", "Haddad", "Brennan", "Tanaka", "Silva"]
GOALS = {
    "tasks": "Run all team projects in one place with clear owners and due dates.",
    "docs": "Move team documentation into one shared workspace that everyone can find and edit.",
    "support": "Give employees a single place to submit and track internal service requests.",
}
COHORTS = [("progressing", 7), ("not_started", 6), ("plan_later", 5), ("technical", 4), ("completed", 5), ("opted_out", 3),
           ("stale_data", 1), ("missing_contact", 1), ("missing_plan", 1), ("guided", 3), ("channel_switch", 2), ("needs_human", 1)]


def base_clock() -> datetime:
    return datetime.combine(date.today(), datetime.min.time()).replace(hour=9)


def ms_keys(product: str, needs_dir: bool) -> list[str]:
    return [m["key"] for m in DEFAULT_MILESTONES[product] if not m.get("applies_if") or needs_dir]


def build_db(seed: int = SEED) -> DB:
    rng = random.Random(seed)
    db = DB()
    db.init_schema()
    now = base_clock()
    db.set_clock(now)
    db.save_settings(Settings())
    db.origin = "seed"

    plan: list[tuple[str, str]] = [("featured", "Maple Design")]
    names = list(NAMES)
    rng.shuffle(names)
    i = 0
    for scen, n in COHORTS:
        for _ in range(n):
            plan.append((scen, names[i])); i += 1

    for idx, (scen, name) in enumerate(plan, start=1):
        aid = f"ACC-{idx:03d}"
        if scen == "featured":
            _maple(db, rng, now)
            continue
        _account(db, rng, now, aid, name if scen != "featured" else "Maple Design", scen)

    # historical resolved work (synthetic)
    done_accts = db.q("SELECT id FROM accounts WHERE scenario IN ('completed','progressing') ORDER BY id LIMIT 6")
    for k, a in enumerate(done_accts):
        prod = "docs" if k % 2 == 0 else "tasks"
        if not db.one("SELECT 1 x FROM subscriptions WHERE account_id=? AND product=?", (a["id"], prod)):
            continue
        j = db.one("SELECT id FROM journeys WHERE account_id=? AND product=?", (a["id"], prod))
        cid = db.next_id("CASE")
        created = now - timedelta(days=rng.randint(20, 50))
        db.insert("support_cases", id=cid, account_id=a["id"], product=prod, subject="Directory sync did not start" if prod == "docs" else "Invitation emails not received",
                  category="integration" if prod == "docs" else "configuration", status="closed", blocking=0, created_at=to_iso(created),
                  resolved_at=to_iso(created + timedelta(days=rng.randint(1, 4))))
        db.insert("human_tasks", id=db.next_id("TSK"), account_id=a["id"], journey_id=j["id"], product=prod, issue="Directory sync did not start",
                  category="integration", priority="medium", team="Technical Support", status="resolved", assignee="Ari (Tech Support)",
                  context="{}", resolution_note="Historical synthetic record.", created_at=to_iso(created), resolved_at=to_iso(created + timedelta(days=2)), case_id=cid)
    seed_catalog(db, now)
    seed_northstar(db, rng, now)
    seed_team_history(db, rng, now)
    from .services import snapshot_seed
    snapshot_seed(db)
    db.origin = "session"
    return db


def _contact(db, rng, aid, name, *, opted=0, email=True, channel="email"):
    first, last = rng.choice(FIRST), rng.choice(LAST)
    slug = "".join(c for c in name.lower() if c.isalnum())
    cid = db.next_id("CON")
    db.insert("contacts", id=cid, account_id=aid, name=f"{first} {last}", email=f"{first.lower()}@{slug}.example" if email else None,
              role="Workspace administrator", is_admin=1, opted_out=opted, preferred_channel=channel, consent=1)
    return cid


def _msg(db, aid, cid, jid, channel, actor, body, ts, *, kind="message", signals=None, docs=None):
    titles = {"DOC-101": "Getting started with Tasks", "DOC-102": "Getting started with Docs", "DOC-103": "Getting started with Support",
              "DOC-104": "Connecting your employee directory to Docs", "DOC-105": "Directory integration troubleshooting"}
    db.insert("interactions", id=db.next_id("INT", 4), account_id=aid, contact_id=cid, journey_id=jid, channel=channel, actor=actor, kind=kind,
              body=body, sources=json.dumps([{"doc_id": d, "title": titles.get(d, d)} for d in (docs or [])]), signals=json.dumps(signals or {}), ts=to_iso(ts))


def _journey(db, aid, product, state, started, paused_until=None, attempted=None, completed=None):
    jid = db.next_id("JRN")
    db.insert("journeys", id=jid, account_id=aid, product=product, state=state, paused_until=to_iso(paused_until) if paused_until else None,
              attempted_docs=json.dumps(attempted or []), started_at=to_iso(started), updated_at=to_iso(started),
              completed_at=to_iso(completed) if completed else None)
    if state == "paused_until_rollout" and paused_until:
        aid_ = db.next_id("ACT")
        db.insert("scheduled_actions", id=aid_, account_id=aid, journey_id=jid, action_type="resume_check", due_at=to_iso(paused_until),
                  status="pending", created_at=to_iso(started), note="Resume when rollout starts")
    return jid


def _events(db, rng, aid, product, start, done: int, now, needs_dir, usage=0, last_gap_days=None):
    keys = ms_keys(product, needs_dir)
    span = max(((now - start).days if last_gap_days is None else (now - start).days - last_gap_days), 0)
    for k, key in enumerate(keys[:done]):
        ts = start + timedelta(days=min(span, int(span * (k + 1) / max(done, 1))), hours=rng.randint(0, 5))
        db.insert("product_events", account_id=aid, product=product, event_type=key, ts=to_iso(min(ts, now)))
    for _ in range(usage):
        db.insert("product_events", account_id=aid, product=product, event_type="usage_session",
                  ts=to_iso(now - timedelta(days=rng.randint(0, 13), hours=rng.randint(0, 8))))


def _maple(db, rng, now):
    aid = "ACC-001"
    db.next_id("ACC")  # keep the account sequence aligned
    db.insert("accounts", id=aid, name="Maple Design", segment="Mid-market", scenario="featured", needs_directory=1,
              goal="Move team documentation into one shared workspace and connect it to our employee directory this quarter.",
              data_refreshed_at=to_iso(now - timedelta(hours=1)), lifecycle="onboarding", owner="Jamie Ortiz", solutions_architect="Morgan Ellis")
    cid = db.next_id("CON")
    db.insert("contacts", id=cid, account_id=aid, name="Jordan Reyes", email="jordan@maple-design.example", role="Workspace administrator",
              is_admin=1, opted_out=0, preferred_channel="email", consent=1)
    for p in PRODUCTS:
        db.insert("subscriptions", id=db.next_id("SUB"), account_id=aid, product=p, bundle=1, status="active")
    starts = {"tasks": now - timedelta(days=40), "docs": now - timedelta(days=7), "support": now + timedelta(days=45)}
    for p, s in starts.items():
        db.insert("rollout_plans", account_id=aid, product=p, planned_start=to_iso(s))
    _events(db, rng, aid, "tasks", starts["tasks"], 4, now, True, usage=11, last_gap_days=6)
    _events(db, rng, aid, "docs", starts["docs"], 1, now, True, usage=2, last_gap_days=6)
    _journey(db, aid, "tasks", "completed", starts["tasks"], completed=now - timedelta(days=8))
    _journey(db, aid, "docs", "monitoring", starts["docs"])
    _journey(db, aid, "support", "paused_until_rollout", now - timedelta(days=30), paused_until=starts["support"])


def _account(db, rng, now, aid, name, scen):
    db.next_id("ACC")
    prods = rng.choice([PRODUCTS, rng.sample(PRODUCTS, 2), rng.sample(PRODUCTS, 2), rng.sample(PRODUCTS, 1)])
    prods = [p for p in PRODUCTS if p in prods]
    focus_pref = {"technical": "docs", "needs_human": "docs", "guided": "docs", "channel_switch": "docs"}.get(scen)
    if focus_pref and focus_pref not in prods:
        prods = [p for p in PRODUCTS if p in prods + [focus_pref]]
    focus = focus_pref or rng.choice(prods)
    needs_dir = int("docs" in prods and rng.random() < 0.6) or int(scen in ("technical", "needs_human", "guided", "channel_switch"))
    refreshed = now - timedelta(days=30) if scen == "stale_data" else now - timedelta(hours=rng.randint(1, 20))
    db.insert("accounts", id=aid, name=name, segment=rng.choice(["SMB", "Mid-market"]), scenario=scen, needs_directory=needs_dir if "docs" in prods else 0,
              goal=GOALS[focus], data_refreshed_at=to_iso(refreshed),
              lifecycle="adoption" if scen == "completed" else "onboarding")
    channel = "chat" if scen == "channel_switch" else "email"
    cid = _contact(db, rng, aid, name, opted=int(scen == "opted_out"), email=scen != "missing_contact", channel=channel)
    bundle = int(len(prods) == 3)
    for p in prods:
        db.insert("subscriptions", id=db.next_id("SUB"), account_id=aid, product=p, bundle=bundle, status="active")
    nd = bool(db.one("SELECT needs_directory n FROM accounts WHERE id=?", (aid,))["n"])

    for p in prods:
        is_focus = p == focus
        later = rng.randint(15, 70)
        if not is_focus or scen == "plan_later":
            start = now + timedelta(days=later)
            if scen != "missing_plan" or not is_focus:
                db.insert("rollout_plans", account_id=aid, product=p, planned_start=to_iso(start))
            state = "monitoring" if (scen == "plan_later" and rng.random() < 0.6) or scen == "missing_plan" else "paused_until_rollout"
            if scen == "opted_out":
                state = "opted_out"
            _journey(db, aid, p, state, now - timedelta(days=20), paused_until=start if state == "paused_until_rollout" else None)
            continue

        # focus product, rollout already started
        total = len(ms_keys(p, nd))
        if scen == "progressing":
            days, done, gap = rng.randint(10, 25), rng.randint(2, max(2, total - 1)), rng.randint(0, 3)
        elif scen == "completed":
            days, done, gap = rng.randint(18, 40), total, rng.randint(3, 15)
        else:
            days, done, gap = rng.randint(7, 14), {"not_started": 0, "guided": 0, "channel_switch": 1, "technical": 1, "needs_human": 1,
                                                  "opted_out": 0, "stale_data": 0, "missing_contact": 0}.get(scen, 0), 1
        start = now - timedelta(days=days)
        if scen != "missing_plan":
            db.insert("rollout_plans", account_id=aid, product=p, planned_start=to_iso(start))
        _events(db, rng, aid, p, start, done, now, nd, usage={"progressing": 9, "completed": 12}.get(scen, rng.randint(0, 2)), last_gap_days=gap)
        _focus_state(db, rng, now, aid, cid, p, scen, start, name)


def _focus_state(db, rng, now, aid, cid, p, scen, start, name):
    guide_body = "Hi, I noticed setup for your workspace paused. The next step is described in our getting-started guide. Reply here if anything is blocking you."
    gdoc = {"tasks": "DOC-101", "docs": "DOC-102", "support": "DOC-103"}[p]
    if scen == "completed":
        _journey(db, aid, p, "completed", start, completed=now - timedelta(days=rng.randint(3, 12)))
    elif scen == "progressing":
        _journey(db, aid, p, "monitoring", start)
    elif scen in ("not_started", "stale_data", "missing_contact", "missing_plan"):
        _journey(db, aid, p, "monitoring", start)
    elif scen == "opted_out":
        jid = _journey(db, aid, p, "opted_out", start)
        _msg(db, aid, cid, jid, "email", "agent", guide_body, now - timedelta(days=9), signals={"message_kind": "proactive", "guidance_docs": [gdoc]}, docs=[gdoc])
        _msg(db, aid, cid, jid, "email", "customer", "Please stop sending messages.", now - timedelta(days=8), signals={"intent": "opt_out"})
    elif scen == "guided":
        jid = _journey(db, aid, p, "waiting_for_customer", start)
        _msg(db, aid, cid, jid, "email", "agent", guide_body, now - timedelta(days=1, hours=2), signals={"message_kind": "proactive", "guidance_docs": [gdoc]}, docs=[gdoc])
        db.insert("scheduled_actions", id=db.next_id("ACT"), account_id=aid, journey_id=jid, action_type="setup_reminder",
                  due_at=to_iso(now + timedelta(days=2)), status="pending", created_at=to_iso(now - timedelta(days=1)), note="Follow up if milestone is still incomplete")
    elif scen == "channel_switch":
        jid = _journey(db, aid, p, "guidance_sent", start)
        _msg(db, aid, cid, jid, "email", "agent", guide_body, now - timedelta(days=2), signals={"message_kind": "proactive", "guidance_docs": [gdoc]}, docs=[gdoc])
        _msg(db, aid, cid, jid, "chat", "customer", "Can we chat instead? Email gets buried. Where do I connect the directory?", now - timedelta(hours=3), signals={"intent": "unknown"})
    elif scen in ("technical", "needs_human"):
        cid_case = db.next_id("CASE")
        db.insert("support_cases", id=cid_case, account_id=aid, product=p, subject="Employee directory will not connect", category="integration",
                  status="open", blocking=1, created_at=to_iso(now - timedelta(days=3)))
        with_task = scen == "needs_human" or rng.random() < 0.5
        state = "waiting_for_human" if with_task else "monitoring"
        jid = _journey(db, aid, p, state, start, attempted=["DOC-104", "DOC-105"] if with_task else [])
        _msg(db, aid, cid, jid, "email", "agent", guide_body, now - timedelta(days=5), signals={"message_kind": "proactive", "guidance_docs": ["DOC-104"]}, docs=["DOC-104"])
        _msg(db, aid, cid, jid, "email", "customer", "The directory connection keeps failing." if scen == "technical" else "I'd like to talk to a person about the directory.",
             now - timedelta(days=4), signals={"intent": "issue_directory"})
        if with_task:
            ctxt = {"goal": GOALS[p], "account": name, "product": p, "summary": "Customer cannot connect directory; documented steps already tried.",
                    "progress": [], "guidance_sent": [], "attempted_doc_ids": ["DOC-104", "DOC-105"], "conversation_refs": []}
            db.insert("human_tasks", id=db.next_id("TSK"), account_id=aid, journey_id=jid, product=p, issue="Employee directory will not connect",
                      category="integration", priority="high" if scen == "needs_human" else "medium", team="Technical Support",
                      status="open", context=json.dumps(ctxt), created_at=to_iso(now - timedelta(days=3)), case_id=cid_case)
