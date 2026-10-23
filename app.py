"""Customer Success Orchestrator - an independent portfolio prototype with synthetic data."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Customer Success Orchestrator", page_icon=":material/hub:", layout="wide")

from cso import services as S  # noqa: E402
from cso import session  # noqa: E402
from cso.llm import DEFAULT_MODEL  # noqa: E402
from cso.ui import help as help_, agent_page, config_page, customer, eval_page, nav, overview, queue_page, style, team_page  # noqa: E402

style.inject()
db = session.get_db()

nav.PAGES.update({
    "overview": st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    "customer": st.Page(customer.render, title="Customer workspace", icon=":material/person:", url_path="customer"),
    "agent": st.Page(agent_page.render, title="Customer onboarding", icon=":material/smart_toy:", url_path="agent"),
    "queue": st.Page(queue_page.render, title="Support tasks", icon=":material/support_agent:", url_path="queue"),
    "team": st.Page(team_page.render, title="Meeting preparation", icon=":material/event_note:", url_path="team"),
    "config": st.Page(config_page.render, title="Journey configuration", icon=":material/tune:", url_path="config"),
    "eval": st.Page(eval_page.render, title="Evaluation", icon=":material/fact_check:", url_path="evaluation"),
})
pg = st.navigation(list(nav.PAGES.values()))

target = st.session_state.pop("_goto", None)  # navigation requested by a button callback
if target and nav.PAGES[target].url_path != pg.url_path:
    st.switch_page(nav.PAGES[target])


def _advance(days):
    S.advance_clock(db, days=days)
    session.flash("info", f"Demo clock moved forward {days} day(s). Scheduled reminders that are now due run when you click “Run pending actions”.")


with st.sidebar:
    st.markdown(style.mode_pill(), unsafe_allow_html=True)
    st.caption(session.mode_hint())
    with st.expander("Try with an AI model"):
        st.markdown("The model chooses which tools to call and writes customer messages and meeting talking points. "
                    "Validation, permissions, review steps and business rules still run in code.")
        st.checkbox("Use an AI model instead of prepared scenarios", key="use_live")
        if session.live_available():
            st.success("An API key is available.")
        else:
            st.info("No API key found. Set `ANTHROPIC_API_KEY` in your environment or Streamlit secrets, or paste a key below for this browser session only.")
        st.text_input("API key (this session only)", type="password", key="user_api_key", help="Held in memory for this session. Never stored, logged or shown.")
        st.text_input("Model", key="live_model", placeholder=DEFAULT_MODEL)
        if st.session_state.get("use_live") and not session.live_available():
            st.warning("The app stays in Demo mode until a key is available. Nothing is silently simulated as an AI model.")
    help_.render_guide()
    st.divider()
    st.markdown(f"**Demo clock**  \n{db.now():%a %b %d, %Y %H:%M}")
    st.caption("A pretend calendar so you can see what happens days later.")
    c = st.columns(3)
    for col, d in zip(c, (1, 3, 7)):
        col.button(f"+{d}d", key=f"adv{d}", on_click=_advance, args=(d,), width="stretch")
    st.button("Reset all demo data", on_click=session.reset_demo, width="stretch", help="Resets both walkthroughs and every change. To reset one customer only, use “Restart this walkthrough”.")
    st.divider()
    style.footer_label()
    st.caption("Your changes are private to this session and reset when it ends.")

pg.run()
