"""Shared visual language (dark theme), badges, message bubbles and the account picker."""
from __future__ import annotations

import html
import json

import streamlit as st

from .. import session
from ..format import when
from ..models import PRODUCT_LABEL, STATE_LABEL
from ..retrieval import get_retriever

STATE_COLOR = {  # (text, background) tuned for the dark theme
    "monitoring": ("#9bbcff", "#1e2f6b"), "guidance_sent": ("#7ce8d6", "#12433f"), "waiting_for_customer": ("#7ce8d6", "#12433f"),
    "paused_until_rollout": ("#c3c8d6", "#343a52"), "waiting_for_human": ("#ffc58a", "#5a3414"),
    "resolved_awaiting_progress_check": ("#d2bcff", "#412a73"), "completed": ("#8ff0ad", "#143f27"), "opted_out": ("#ffa3b8", "#59182f"),
    "generated": ("#9bbcff", "#1e2f6b"), "reviewed": ("#d2bcff", "#412a73"), "accepted": ("#8ff0ad", "#143f27"), "edited": ("#8ff0ad", "#143f27"),
    "dismissed": ("#ffa3b8", "#59182f"), "deferred": ("#ffc58a", "#5a3414"), "discussed": ("#7ce8d6", "#12433f"), "withdrawn": ("#c3c8d6", "#343a52"),
}

CSS = """
<style>
:root { --ink:#f1f0ff; --muted:#aaa6d6; --line:#33306b; --soft:#1a1545; --brand:#8b8cf8; }
.stApp { background: radial-gradient(1200px 600px at 70% -10%, #2a1f6b 0%, #120e33 55%); }
[data-testid="stSidebar"] { background:#0e0a2a; border-right:1px solid var(--line); }
.block-container { padding-top: 2.2rem; max-width: 1280px; }
h1, h2, h3, h4 { letter-spacing: -0.01em; }
[data-testid="stMetric"] { background:rgba(139,140,248,0.08); border:1px solid var(--line); border-radius:14px; padding:14px 16px; }
[data-testid="stMetricLabel"] p { white-space:normal !important; line-height:1.25; }
.cso-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem; font-weight:600; white-space:nowrap; }
.cso-pill { display:inline-block; padding:1px 8px; border-radius:6px; font-size:0.74rem; background:var(--soft); color:var(--muted); border:1px solid var(--line); margin-right:4px; }
.cso-msg { border-radius:12px; padding:12px 14px; margin:10px 0 2px 0; font-size:0.94rem; line-height:1.5; border:1px solid var(--line); }
.cso-msg .meta { font-size:0.74rem; color:var(--muted); margin-bottom:4px; font-weight:600; letter-spacing:0.02em; text-transform:uppercase; }
.cso-customer { background:#171a4d; border-left:4px solid #60a5fa; margin-right:12%; }
.cso-agent { background:#2b2470; border-left:4px solid #a78bfa; margin-left:12%; }
.cso-human { background:#3a2a22; border-left:4px solid #f0a050; margin-left:6%; margin-right:6%; }
.cso-system { background:var(--soft); border-left:4px solid #6c6aa8; font-size:0.84rem; color:var(--muted); }
.cso-strip { color:var(--muted); font-size:0.8rem; }
.cso-mode { display:inline-block; padding:3px 10px; border-radius:6px; font-weight:700; font-size:0.8rem; }
.cso-mode.scripted { background:#3b3170; color:#d9d3ff; } .cso-mode.live { background:#14523a; color:#9af0c4; }
.cso-card { border:1px solid var(--line); border-radius:14px; padding:16px 18px; background:rgba(139,140,248,0.06); }
blockquote { border-left:3px solid var(--brand); color:var(--ink) !important; background:rgba(139,140,248,0.08); padding:8px 14px; border-radius:6px; }
.cso-hero { font-size:1.15rem; line-height:1.55; }
.cso-kpi { font-size:0.8rem; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted); }
</style>
"""


STATE_LABEL_ = STATE_LABEL


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def badge(state: str, label: str | None = None) -> str:
    fg, bg = STATE_COLOR.get(state, ("#d9d6ff", "#2b2760"))
    text = label or STATE_LABEL.get(state) or state.replace("_", " ").capitalize()
    return f'<span class="cso-badge" style="color:{fg};background:{bg}">{html.escape(text)}</span>'


def product_pill(p: str) -> str:
    return f'<span class="cso-pill">{html.escape(PRODUCT_LABEL.get(p, p))}</span>'


def mode_pill() -> str:
    cls = "live" if session.mode() == "live" else "scripted"
    return f'<span class="cso-mode {cls}">{html.escape(session.mode_label())}</span>'


def _fmt(s: str) -> str:
    return html.escape(s).replace("\n", "<br>")


def show_sources(srcs: list[dict], key: str):
    """Document titles with the relevant sections; each document opens to its excerpt."""
    if not srcs:
        return
    ret = get_retriever()
    for s in srcs:
        secs = s.get("sections") or []
        label = f"{s['title']} ({s['doc_id']})" + (f" · {', '.join(secs)}" if secs else "")
        with st.expander(f"Source: {label}"):
            chunks = ret.get(s["doc_id"])
            shown = [c for c in chunks if c.section in secs] or chunks
            for c in shown:
                st.markdown(f"**{c.section}**\n\n{c.text}")
            if s.get("xref"):
                st.caption("Also referenced by the message above.")


def bubble(row: dict):
    actor = row["actor"]
    cls = {"customer": "cso-customer", "agent": "cso-agent", "human": "cso-human"}.get(actor, "cso-system")
    who = {"customer": "Customer", "agent": "Assistant", "human": "Support team", "system": "System"}[actor]
    body = row["body"]
    subject = None
    if body.startswith("Subject: "):
        subject, _, body = body.partition("\n\n")
        subject = subject[9:]
    ch = row["channel"] if row["channel"] in ("email", "chat") else ""
    ts = when(row["ts"])
    meta = f"{who} · {ch} · {ts}" if ch else f"{who} · {ts}"
    subj = f"<div style='font-weight:600;margin-bottom:4px'>{html.escape(subject)}</div>" if subject else ""
    st.markdown(f'<div class="cso-msg {cls}"><div class="meta">{html.escape(meta)}</div>{subj}{_fmt(body)}</div>', unsafe_allow_html=True)
    show_sources(json.loads(row.get("sources") or "[]"), row["id"])


# ------------------------------------------------------------ selection ---
def _on_acct():
    session.select(st.session_state.get("w_acct"))  # choosing another customer also leaves a guided walkthrough, keeping its progress


def _on_prod():
    st.session_state["prod"] = st.session_state.get("w_prod")


def account_picker(db, with_product: bool = True) -> tuple[str | None, str | None]:
    """Customer (and product) selectors driven by the canonical session values and stable IDs."""
    accts = db.q("SELECT id, name FROM accounts ORDER BY CASE WHEN id IN ('ACC-001','ACC-041') THEN 0 ELSE 1 END, name")
    ids = [a["id"] for a in accts]
    names = {a["id"]: a["name"] for a in accts}
    cur = st.session_state.get("acct")
    if cur not in ids:
        cur = None
        st.session_state["acct"] = None
    st.session_state["w_acct"] = cur  # keep the widget in step with what is actually displayed
    c1, c2 = st.columns([2, 3])
    c1.selectbox("Customer", ids, index=None, format_func=lambda i: names[i], placeholder="Select a customer…", key="w_acct", on_change=_on_acct)
    if cur is None:
        return None, None
    jid = None
    if with_product:
        js = db.q("SELECT id, product, state FROM journeys WHERE account_id=? ORDER BY product", (cur,))
        prods = [j["product"] for j in js]
        if not prods:
            return cur, None
        prod = st.session_state.get("prod")
        if prod not in prods:
            prod = prods[0]
            st.session_state["prod"] = prod
        st.session_state["w_prod"] = prod
        c2.radio("Product", prods, format_func=lambda p: PRODUCT_LABEL[p], horizontal=True, key="w_prod", on_change=_on_prod)
        jid = next(j["id"] for j in js if j["product"] == prod)
    return cur, jid


def footer_label():
    st.caption("Independent portfolio prototype • Sample data")



def context_line(db, aid: str, prod: str | None = None, label: str | None = None):
    """Show which customer (and product) this screen is about."""
    name = db.one("SELECT name FROM accounts WHERE id=?", (aid,))["name"]
    from ..models import PRODUCT_LABEL
    tail = f" · Product: {PRODUCT_LABEL[prod]}" if prod else ""
    st.markdown(f"**Customer: {name}**{tail}" + (f" &nbsp; <span class='cso-pill'>{html.escape(label)}</span>" if label else ""), unsafe_allow_html=True)
