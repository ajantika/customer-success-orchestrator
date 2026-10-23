"""Per-visitor session state: database, canonical selection, navigation requests, mode and flash messages.

Selection lives in plain session keys ("acct", "prod", "task", "meeting"), never only in widget keys:
Streamlit drops a widget's state when the widget is not rendered in a run (for example on another page) and
creates a new widget when its options or labels change. Pages mirror the canonical values into widgets on every run.
"""
from __future__ import annotations

import streamlit as st

from .datagen import NORTHSTAR, build_db
from .db import DB
from .llm import DEFAULT_MODEL, get_api_key
from .restart import restart_workflow

FEATURED = "ACC-001"


def get_db() -> DB:
    if "db" not in st.session_state:
        st.session_state["db"] = build_db()
        st.session_state.setdefault("acct", None)
        st.session_state.setdefault("prod", "docs")
        st.session_state.setdefault("nonce", 0)
    return st.session_state["db"]


WORKFLOW_ACCT = {"onboarding": FEATURED, "team": NORTHSTAR}


def select(acct: str | None, prod: str | None = None, **extra):
    """Set the selected customer. Choosing a different customer leaves any guided walkthrough (its progress is kept)."""
    g = st.session_state.get("guided")
    if g and WORKFLOW_ACCT.get(g) != acct:
        st.session_state.pop("guided", None)
    st.session_state["acct"] = acct
    if prod:
        st.session_state["prod"] = prod
    for k, v in extra.items():
        st.session_state[k] = v


def goto(page_key: str):
    """Ask app.py to open a page on the next run (safe to call from callbacks)."""
    st.session_state["_goto"] = page_key


def reset_demo():
    for k in ("flash", "guided", "last_scan", "reply_text", "sel_run", "task", "meeting", "_latest_run", "tab_agent", "tab_eval", "viewed", "last_action", "team_scan", "done_onboarding", "done_team"):
        st.session_state.pop(k, None)
    st.session_state["db"] = build_db()
    select(None, "docs")
    st.session_state["nonce"] = st.session_state.get("nonce", 0) + 1
    flash("success", "Demo data reset to the seeded state.")


def _start(which: str, acct: str, **extra):
    """Open a walkthrough. Only that walkthrough's customer is restarted; the other workflow keeps its progress."""
    restart_workflow(get_db(), which)
    select(acct, "docs", **extra)
    st.session_state["guided"] = which
    for k in ("flash", "last_action", "sel_run", "_latest_run", "reply_text", "team_scan", "tab_agent"):
        st.session_state.pop(k, None)
    goto("agent" if which == "onboarding" else "team")


def start_onboarding_demo():
    _start("onboarding", FEATURED)


def start_team_demo():
    _start("team", NORTHSTAR, meeting="MTG-001")


def flash(kind: str, msg: str):
    st.session_state["flash"] = (kind, msg)


def show_flash():
    f = st.session_state.pop("flash", None)
    if f:
        getattr(st, f[0])(f[1])


def live_available() -> bool:
    return bool(get_api_key(st.session_state.get("user_api_key")))


def mode() -> str:
    return "live" if st.session_state.get("use_live") and live_available() else "scripted"


def model_name() -> str:
    return (st.session_state.get("live_model") or "").strip() or DEFAULT_MODEL


def llm_settings() -> dict | None:
    if mode() != "live":
        return None
    return {"api_key": get_api_key(st.session_state.get("user_api_key")), "model": model_name()}


def mode_label() -> str:
    return "Live AI" if mode() == "live" else "Demo mode"


def mode_hint() -> str:
    return "An AI model chooses tools and writes messages; rules still run in code." if mode() == "live" else "Uses prepared responses and rules. No AI model is called."


def record_action(did: str, found: list[str] | None = None, why: str = "", tone: str = "success", run_id: str | None = None, detail: str | None = None,
                  scope: tuple[str, ...] | None = None, task_id: str | None = None, account_id: str | None = None):
    """Remember the result of the last action. It is shown only on the pages named in `scope`, so a result never turns up in an unrelated workflow."""
    st.session_state["last_action"] = {"found": found or [], "did": did, "why": why, "tone": tone, "run_id": run_id, "detail": detail, "scope": scope, "task_id": task_id,
                                      "account_id": account_id or st.session_state.get("acct")}
    try:
        st.toast(did[:140], icon="✅" if tone == "success" else "⚠️" if tone in ("warning", "error") else "ℹ️")
    except Exception:
        pass


def open_task(task_id: str):
    """Open one specific support task, with its customer and product selected."""
    db = st.session_state["db"]
    t = db.one("SELECT account_id, product FROM human_tasks WHERE id=?", (task_id,))
    select(t["account_id"], t["product"])
    st.session_state["task"] = task_id
    st.session_state["queue_scope"] = "customer"
    goto("queue")


def show_action(scope: str | None = None, any_customer: bool = False):
    """One short result message; the longer 'what happened and why' sits in an expander.

    A result belongs to the page named in its scope and to the customer it was about, so it never shows up under another customer or workflow."""
    a = st.session_state.get("last_action")
    if not a or (scope and a.get("scope") and scope not in a["scope"]):
        return
    if scope in ("agent", "queue") and not any_customer and a.get("account_id") and a["account_id"] != st.session_state.get("acct"):
        return
    icon = {"success": "✅", "warning": "⚠️", "error": "⛔", "info": "ℹ️"}.get(a["tone"], "✅")
    with st.container(border=True):
        st.markdown(f"{icon} **{a['did']}**")
        if a.get("task_id"):
            st.button(f"Open support task {a['task_id']}", key=f"ot_{a['task_id']}", on_click=open_task, args=(a["task_id"],))
        if a.get("detail") or a["found"] or a["why"]:
            with st.expander("Details: what happened and why"):
                if a.get("detail"):
                    st.markdown(f"**What the assistant did.** {a['detail']}")
                if a["found"]:
                    st.markdown("**What it found**\n" + "\n".join(f"- {x}" for x in a["found"]))
                if a["why"]:
                    st.markdown(f"**Why.** {a['why']}")
        if a["tone"] == "error":
            st.caption("Nothing was changed by the failed step. Try the action again, or choose “Restart this walkthrough” to start clean.")


def report_run(res: dict):
    """Turn an agent run result into a visible card. Errors are never hidden or replaced by prepared output."""
    from .ui import narrate
    if res.get("deduplicated"):
        record_action(res["summary"], tone="info", why="The same action was already done, so nothing was repeated.", scope=("agent", "team"))
    elif res.get("run_id"):
        d = narrate.from_run(st.session_state["db"], res["run_id"])
        if res.get("outcome") == "error":
            d["short"] = "The AI model could not be reached. Nothing was changed."
            d["did"] = f"The AI model call failed: {res.get('error')} Your session and data are unchanged by the failed call."
        run = st.session_state["db"].one("SELECT trigger, account_id FROM agent_runs WHERE id=?", (res["run_id"],))
        run_acct = run["account_id"] if run else None
        record_action(d["short"], d["found"], d["why"], d["tone"], res["run_id"], detail=d["did"], account_id=run_acct,
                      scope=("team",) if run and run["trigger"] == "meeting_prep" else ("agent",), task_id=d.get("task_id"))
    else:
        record_action(res.get("summary", "Done."))
    st.session_state.pop("flash", None)
