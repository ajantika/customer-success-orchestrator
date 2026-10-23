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

FEATURED = "ACC-001"


def get_db() -> DB:
    if "db" not in st.session_state:
        st.session_state["db"] = build_db()
        st.session_state.setdefault("acct", None)
        st.session_state.setdefault("prod", "docs")
        st.session_state.setdefault("nonce", 0)
    return st.session_state["db"]


def select(acct: str | None, prod: str | None = None, **extra):
    st.session_state["acct"] = acct
    if prod:
        st.session_state["prod"] = prod
    for k, v in extra.items():
        st.session_state[k] = v


def goto(page_key: str):
    """Ask app.py to open a page on the next run (safe to call from callbacks)."""
    st.session_state["_goto"] = page_key


def reset_demo():
    for k in ("flash", "guided", "last_scan", "reply_text", "sel_run", "task", "meeting", "_latest_run", "tab_agent", "tab_eval", "viewed"):
        st.session_state.pop(k, None)
    st.session_state["db"] = build_db()
    select(None, "docs")
    st.session_state["nonce"] = st.session_state.get("nonce", 0) + 1
    flash("success", "Demo data reset to the seeded state.")


def start_onboarding_demo():
    reset_demo()
    select(FEATURED, "docs")
    st.session_state["guided"] = "onboarding"
    st.session_state.pop("flash", None)
    goto("agent")


def start_team_demo():
    reset_demo()
    select(NORTHSTAR, "docs", meeting="MTG-001")
    st.session_state["guided"] = "team"
    st.session_state.pop("flash", None)
    goto("team")


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
    return "An AI model chooses tools and writes messages; rules still run in code." if mode() == "live" else "Uses prepared scenarios and rules. No AI model is called."


def report_run(res: dict):
    """Turn an agent run result into a visible message. Errors are never hidden or replaced by scripted output."""
    if res.get("deduplicated"):
        flash("info", res["summary"])
    elif res.get("outcome") == "error":
        flash("error", f"Live AI run failed: {res.get('error')} Your session and data are unchanged by the failed call.")
    elif res.get("outcome") == "step_limit":
        flash("warning", "The agent reached its step limit and stopped. " + res["summary"])
    else:
        flash("success", res["summary"])
