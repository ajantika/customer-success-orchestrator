"""Per-visitor session state: database, mode and flash messages."""
from __future__ import annotations

import streamlit as st

from .datagen import build_db
from .db import DB
from .llm import get_api_key, get_model

FEATURED = "ACC-001"


def get_db() -> DB:
    if "db" not in st.session_state:
        st.session_state["db"] = build_db()
        st.session_state.setdefault("sel_acc", FEATURED)
        st.session_state.setdefault("sel_prod", "docs")
        st.session_state.setdefault("nonce", 0)
    return st.session_state["db"]


def reset_demo():
    for k in ("flash", "guided", "last_scan", "reply_text", "sel_run"):
        st.session_state.pop(k, None)
    st.session_state["db"] = build_db()
    st.session_state["sel_acc"], st.session_state["sel_prod"] = FEATURED, "docs"
    st.session_state["nonce"] = st.session_state.get("nonce", 0) + 1
    flash("success", "Demo data reset to the seeded state.")


def flash(kind: str, msg: str):
    st.session_state["flash"] = (kind, msg)


def show_flash():
    f = st.session_state.pop("flash", None)
    if f:
        getattr(st, f[0])(f[1])


def live_available() -> bool:
    return bool(get_api_key(st.session_state.get("user_api_key")))


def mode() -> str:
    return "live" if st.session_state.get("mode_choice") == "Live AI" and live_available() else "scripted"


def llm_settings() -> dict | None:
    if mode() != "live":
        return None
    return {"api_key": get_api_key(st.session_state.get("user_api_key")), "model": get_model()}


def mode_label() -> str:
    return "Live AI" if mode() == "live" else "Scripted demo"


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
