from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from .. import rules, session
from ..models import PRODUCT_LABEL, TEAMS, Settings
from . import style


def _ms_rows(cur: Settings, p: str) -> pd.DataFrame:
    df = pd.DataFrame([{"Key": m["key"], "Label": m["label"], "Enabled": m.get("enabled", True)} for m in cur.milestones[p]])
    ed = st.session_state.get(f"ms_ed_{p}")
    if isinstance(ed, dict):
        for idx, ch in ed.get("edited_rows", {}).items():
            for k, v in ch.items():
                df.loc[int(idx), k] = v
    return df


def _proposed(db) -> tuple[Settings | None, str | None]:
    cur = db.get_settings()
    ss = st.session_state
    ms = {}
    for p in cur.milestones:
        rows = _ms_rows(cur, p)
        ms[p] = [{**m, "label": str(r["Label"]).strip() or m["label"], "enabled": bool(r["Enabled"])} for m, (_, r) in zip(cur.milestones[p], rows.iterrows())]
    try:
        return Settings(
            stall_threshold_days=ss["cfg_stall"], max_messages_per_7d=ss["cfg_max7"], min_hours_between_messages=ss["cfg_gap"],
            reminder_interval_days=ss["cfg_rem"], stale_data_days=ss["cfg_stale"], max_unanswered_messages=ss["cfg_unans"],
            max_agent_steps=ss["cfg_steps"], stop_on_blocking_case=ss["cfg_stopcase"], handoff_on_tried_steps=ss["cfg_tried"],
            max_troubleshooting_replies=ss["cfg_trbl"], offer_handoff_when_docs_unsupported=ss["cfg_offer"],
            team_integration=ss["cfg_t1"], team_configuration=ss["cfg_t2"], team_docs_gap=ss["cfg_t3"], team_other=ss["cfg_t4"],
            fault_create_handoff=cur.fault_create_handoff, milestones=ms), None
    except ValidationError as e:
        return None, "; ".join(f"{x['loc'][0]}: {x['msg']}" for x in e.errors())


def _save(db):
    s, err = _proposed(db)
    if err:
        session.flash("error", "Not saved: " + err)
        return
    if not any(m["enabled"] for ms in s.milestones.values() for m in ms):
        session.flash("error", "Not saved: at least one milestone must stay enabled.")
        return
    db.save_settings(s)
    session.flash("success", "Journey policy saved for this session.")


def render():
    db = session.get_db()
    session.show_flash()
    st.title("Journey configuration")
    st.warning("These values are a **demo policy**, not a universally valid customer-success threshold. Real thresholds should be set from your own data.")
    cur = db.get_settings()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Eligibility and outreach frequency")
        c1, c2 = st.columns(2)
        c1.number_input("Stalled-setup threshold (days without milestone progress)", 1, 30, cur.stall_threshold_days, key="cfg_stall",
                        help="After the planned rollout start, outreach is allowed only when no milestone has completed for this many days.")
        c2.number_input("Stale data limit (days)", 1, 90, cur.stale_data_days, key="cfg_stale", help="Older product data is flagged for review instead of used for outreach.")
        c1.number_input("Max proactive messages per 7 days", 1, 7, cur.max_messages_per_7d, key="cfg_max7")
        c2.number_input("Minimum hours between messages", 0, 168, cur.min_hours_between_messages, key="cfg_gap")
        c1.number_input("Reminder interval after guidance (days)", 1, 14, cur.reminder_interval_days, key="cfg_rem")
        c2.number_input("Max agent steps per run", 3, 15, cur.max_agent_steps, key="cfg_steps", help="Hard limit on tool calls in one agent run.")
        st.subheader("Stopping conditions")
        st.checkbox("Always stop when setup is complete", True, disabled=True, help="Fixed rule.")
        st.checkbox("Always stop when the customer opts out", True, disabled=True, help="Fixed rule.")
        st.checkbox("Hold reminders while a blocking support case is open", cur.stop_on_blocking_case, key="cfg_stopcase")
        st.number_input("Stop after this many unanswered proactive messages", 1, 6, cur.max_unanswered_messages, key="cfg_unans")
        st.subheader("Escalation criteria")
        st.checkbox("Escalate when the customer says they already tried the documented steps", cur.handoff_on_tried_steps, key="cfg_tried")
        st.number_input("Escalate after this many troubleshooting replies", 1, 5, cur.max_troubleshooting_replies, key="cfg_trbl")
        st.checkbox("Offer a handoff when documentation does not support an answer", cur.offer_handoff_when_docs_unsupported, key="cfg_offer")
        st.subheader("Human team ownership")
        t = st.columns(2)
        t[0].selectbox("Integration issues", TEAMS, TEAMS.index(cur.team_integration), key="cfg_t1")
        t[1].selectbox("Configuration issues", TEAMS, TEAMS.index(cur.team_configuration), key="cfg_t2")
        t[0].selectbox("Documentation gaps", TEAMS, TEAMS.index(cur.team_docs_gap), key="cfg_t3")
        t[1].selectbox("Other issues", TEAMS, TEAMS.index(cur.team_other), key="cfg_t4")
        st.subheader("Onboarding milestones")
        st.caption("Rename or switch off milestones. “Required integration connected” only applies to accounts that need a directory.")
        for p, ms in cur.milestones.items():
            st.markdown(f"**{PRODUCT_LABEL[p]}**")
            base = pd.DataFrame([{"Key": m["key"], "Label": m["label"], "Enabled": m.get("enabled", True)} for m in ms])
            st.data_editor(base, key=f"ms_ed_{p}", hide_index=True, disabled=["Key"], width="stretch",
                           column_config={"Label": st.column_config.TextColumn(required=True)})
        st.button("Save policy", type="primary", on_click=_save, args=(db,))
    with right:
        st.subheader("Effect on an example account")
        prop, err = _proposed(db)
        if err:
            st.error("Invalid values: " + err)
            return
        accts = db.q("SELECT a.id, a.name, j.id jid, j.product, j.state FROM accounts a JOIN journeys j ON j.account_id=a.id ORDER BY a.id, j.product")
        pick = st.selectbox("Example journey", [a["jid"] for a in accts],
                            format_func=lambda x: next(f"{a['name']} · {PRODUCT_LABEL[a['product']]}" for a in accts if a["jid"] == x))
        now_el, new_el = rules.evaluate_outreach(db, pick), rules.evaluate_outreach(db, pick, settings=prop)
        for title, el in (("Saved policy", now_el), ("Proposed (unsaved) policy", new_el)):
            with st.container(border=True):
                st.markdown(f"**{title}:** " + ("✅ eligible for proactive outreach" if el.allowed else "⛔ not eligible"))
                for c in el.checks:
                    st.markdown(f"{'✅' if c.passed else '❌'} {c.message}")
        if now_el.allowed != new_el.allowed:
            st.info("This change would flip the decision for this account.")
        st.caption("Rules read these values on every check. Milestone edits change what counts as “complete”.")
