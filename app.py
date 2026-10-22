"""Customer Success Orchestrator - an independent portfolio prototype with synthetic data."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Customer Success Orchestrator", page_icon=":material/hub:", layout="wide")

from cso import session  # noqa: E402
from cso.ui import agent_page, config_page, customer, eval_page, nav, overview, queue_page, style  # noqa: E402
from cso import services as S  # noqa: E402

style.inject()
db = session.get_db()

nav.PAGES.update({
    "overview": st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    "customer": st.Page(customer.render, title="Customer workspace", icon=":material/person:", url_path="customer"),
    "agent": st.Page(agent_page.render, title="Agent workspace", icon=":material/smart_toy:", url_path="agent"),
    "queue": st.Page(queue_page.render, title="Human work queue", icon=":material/support_agent:", url_path="queue"),
    "config": st.Page(config_page.render, title="Journey configuration", icon=":material/tune:", url_path="config"),
    "eval": st.Page(eval_page.render, title="Evaluation", icon=":material/fact_check:", url_path="evaluation"),
})
pg = st.navigation(list(nav.PAGES.values()))


def _advance(days):
    S.advance_clock(db, days=days)
    session.flash("info", f"Demo clock advanced {days} day(s). Use “Run pending actions” to execute anything now due.")


with st.sidebar:
    st.markdown(f'<span class="cso-mode {"live" if session.mode() == "live" else "scripted"}">{session.mode_label()}</span>', unsafe_allow_html=True)
    st.radio("Agent mode", ["Scripted demo", "Live AI"], key="mode_choice", help="Scripted demo uses deterministic rules. Live AI lets a language model choose tools.")
    if st.session_state.get("mode_choice") == "Live AI":
        if session.live_available():
            st.caption("Live AI enabled. Calls use the same tools and rules.")
        else:
            st.warning("No API key found, so the app stays in Scripted demo. Set ANTHROPIC_API_KEY (or Streamlit secrets), or paste a key for this session only.")
        st.text_input("API key (this session only)", type="password", key="user_api_key", help="Held in memory for this browser session. Never stored or shown.")
    st.divider()
    st.markdown(f"**Demo clock**  \n{db.now():%a %b %d, %Y %H:%M}")
    c = st.columns(3)
    for col, d in zip(c, (1, 3, 7)):
        col.button(f"+{d}d", key=f"adv{d}", on_click=_advance, args=(d,), width="stretch")
    st.button("Reset demo data", on_click=session.reset_demo, width="stretch")
    st.divider()
    style.footer_label()
    st.caption("State is private to your session and resets when it ends.")

pg.run()
