"""Shared visual language: colours, badges, message bubbles, account picker."""
from __future__ import annotations

import html
import json

import streamlit as st

from ..models import PRODUCT_LABEL, STATE_LABEL
from ..retrieval import get_retriever

STATE_COLOR = {
    "monitoring": ("#1d4ed8", "#e8efff"), "guidance_sent": ("#0f766e", "#def7f3"), "waiting_for_customer": ("#0f766e", "#def7f3"),
    "paused_until_rollout": ("#4b5563", "#eceef2"), "waiting_for_human": ("#9a3412", "#ffeedd"),
    "resolved_awaiting_progress_check": ("#6d28d9", "#efe9ff"), "completed": ("#166534", "#dcf5e4"), "opted_out": ("#9f1239", "#fde8ee"),
}

CSS = """
<style>
:root { --ink:#1f2937; --muted:#5b6472; --line:#e3e7ee; --soft:#f4f6fb; --brand:#3b4cca; }
.block-container { padding-top: 2.2rem; max-width: 1280px; }
h1, h2, h3 { letter-spacing: -0.01em; color: var(--ink); }
.cso-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem; font-weight:600; white-space:nowrap; }
.cso-pill { display:inline-block; padding:1px 8px; border-radius:6px; font-size:0.74rem; background:var(--soft); color:var(--muted); border:1px solid var(--line); margin-right:4px; }
.cso-msg { border-radius:12px; padding:12px 14px; margin:10px 0 2px 0; font-size:0.94rem; line-height:1.5; border:1px solid var(--line); }
.cso-msg .meta { font-size:0.74rem; color:var(--muted); margin-bottom:4px; font-weight:600; letter-spacing:0.02em; text-transform:uppercase; }
.cso-customer { background:#ffffff; border-left:4px solid #1d4ed8; margin-right:12%; }
.cso-agent { background:#eef0ff; border-left:4px solid #3b4cca; margin-left:12%; }
.cso-human { background:#fff6e5; border-left:4px solid #b45309; margin-left:6%; margin-right:6%; }
.cso-system { background:var(--soft); border-left:4px solid #9aa3b2; font-size:0.84rem; color:var(--muted); }
.cso-strip { color:var(--muted); font-size:0.8rem; }
.cso-card { border:1px solid var(--line); border-radius:12px; padding:14px 16px; background:#fff; }
.cso-ok { color:#166534; font-weight:600; } .cso-no { color:#9f1239; font-weight:600; }
.cso-mode { display:inline-block; padding:3px 10px; border-radius:6px; font-weight:700; font-size:0.8rem; }
.cso-mode.scripted { background:#fff3cd; color:#7a5200; } .cso-mode.live { background:#dcf5e4; color:#166534; }
</style>
"""


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def badge(state: str) -> str:
    fg, bg = STATE_COLOR.get(state, ("#374151", "#eceef2"))
    return f'<span class="cso-badge" style="color:{fg};background:{bg}">{html.escape(STATE_LABEL.get(state, state))}</span>'


def product_pill(p: str) -> str:
    return f'<span class="cso-pill">{html.escape(PRODUCT_LABEL.get(p, p))}</span>'


def _fmt(s: str) -> str:
    return html.escape(s).replace("\n", "<br>")


def bubble(row: dict):
    actor = row["actor"]
    cls = {"customer": "cso-customer", "agent": "cso-agent", "human": "cso-human"}.get(actor, "cso-system")
    who = {"customer": "Customer", "agent": "Onboarding agent", "human": "Human operator", "system": "System"}[actor]
    body = row["body"]
    subject = None
    if body.startswith("Subject: "):
        subject, _, body = body.partition("\n\n")
        subject = subject[9:]
    ch = row["channel"] if row["channel"] in ("email", "chat") else ""
    meta = f"{who} · {ch} · {row['ts'].replace('T', ' ')[:16]}" if ch else f"{who} · {row['ts'].replace('T', ' ')[:16]}"
    subj = f"<div style='font-weight:600;margin-bottom:4px'>{html.escape(subject)}</div>" if subject else ""
    st.markdown(f'<div class="cso-msg {cls}"><div class="meta">{html.escape(meta)}</div>{subj}{_fmt(body)}</div>', unsafe_allow_html=True)
    srcs = json.loads(row.get("sources") or "[]")
    if srcs:
        with st.expander(f"Sources ({len(srcs)}): " + ", ".join(s["doc_id"] for s in srcs)):
            for s in srcs:
                st.markdown(f"**{s['doc_id']} · {s['title']}**")
                for c in get_retriever().get(s["doc_id"]):
                    st.markdown(f"*{c.section}*\n\n{c.text}")


def account_picker(db, key: str = "sel_acc", with_product: bool = True) -> tuple[str, str | None]:
    accts = db.q("SELECT id, name, scenario FROM accounts ORDER BY CASE id WHEN 'ACC-001' THEN 0 ELSE 1 END, name")
    ids = [a["id"] for a in accts]
    labels = {a["id"]: f"{a['name']} ({a['id']})" for a in accts}
    if st.session_state.get(key) not in ids:
        st.session_state[key] = ids[0]
    c1, c2 = st.columns([2, 3])
    aid = c1.selectbox("Customer", ids, format_func=labels.get, key=key)
    jid = None
    if with_product:
        js = db.q("SELECT id, product, state FROM journeys WHERE account_id=? ORDER BY product", (aid,))
        prods = [j["product"] for j in js]
        if st.session_state.get("sel_prod") not in prods and prods:
            st.session_state["sel_prod"] = prods[0]
        prod = c2.radio("Product journey", prods, format_func=lambda p: f"{PRODUCT_LABEL[p]} · {STATE_LABEL[next(j['state'] for j in js if j['product'] == p)]}",
                        horizontal=True, key="sel_prod")
        jid = next((j["id"] for j in js if j["product"] == prod), None)
    return aid, jid


def footer_label():
    st.caption("Independent portfolio prototype • Synthetic customer data")
