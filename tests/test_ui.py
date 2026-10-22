"""UI smoke tests with Streamlit's AppTest: every page renders and the guided journey works through real button clicks."""
import pytest
from streamlit.testing.v1 import AppTest


def _script(page: str):
    import streamlit as st
    from cso import session
    from cso.ui import agent_page, config_page, customer, eval_page, nav, overview, queue_page, style
    mods = {"overview": overview, "customer": customer, "agent": agent_page, "queue": queue_page, "config": config_page, "eval": eval_page}
    nav.PAGES.update({k: st.Page(m.render, title=k, url_path=k) for k, m in mods.items()})
    style.inject()
    session.get_db()
    if st.session_state.get("sel_acc") is None and not st.session_state.get("_picked"):
        st.session_state["sel_acc"] = "ACC-001"
    mods[st.session_state.get("_page", page)].render()


def _at(page):
    at = AppTest.from_function(_script, args=(page,), default_timeout=60)
    at.run()
    return at


@pytest.mark.parametrize("page", ["overview", "customer", "agent", "queue", "config", "eval"])
def test_pages_render_without_exceptions(page):
    at = _at(page)
    assert not at.exception, [e.value for e in at.exception]


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def test_guided_journey_via_clicks_no_duplicates():
    at = _at("agent")
    at.session_state["guided"] = True
    at.run()
    _btn(at, "Run onboarding check").click().run()
    db = at.session_state["db"]
    n = db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"]
    assert n == 1 and not at.exception
    at.run()  # a plain rerun must not send anything
    at.run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    _btn(at, "The directory connection is failing.").click().run()
    _btn(at, "We already tried those instructions.").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    assert db.one("SELECT state FROM journeys WHERE account_id='ACC-001' AND product='docs'")["state"] == "waiting_for_human"
    assert not at.exception, [e.value for e in at.exception]


def test_full_maple_journey_through_ui():
    at = _at("agent")
    db = at.session_state["db"]
    _btn(at, "Run onboarding check").click().run()
    _btn(at, "The directory connection is failing.").click().run()
    _btn(at, "We already tried those instructions.").click().run()
    # operator resolves the task on the queue page; note is required
    at.session_state["_page"] = "queue"
    at.run()
    assert _btn(at, "Resolve task").disabled
    next(t for t in at.text_area if t.label.startswith("Resolution note")).set_value("Re-issued the directory token and verified sync.").run()
    _btn(at, "Resolve task").click().run()
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1
    assert db.one("SELECT state FROM journeys WHERE account_id='ACC-001' AND product='docs'")["state"] != "completed"
    # customer reports completion; synthetic events are generated first
    at.session_state["_page"] = "agent"
    at.run()
    _btn(at, "Setup is now complete.").click().run()
    assert db.one("SELECT state FROM journeys WHERE account_id='ACC-001' AND product='docs'")["state"] == "completed"
    assert db.one("SELECT COUNT(*) n FROM scheduled_actions WHERE account_id='ACC-001' AND status='pending' AND action_type='setup_reminder' AND journey_id IN (SELECT id FROM journeys WHERE product='docs')")["n"] == 0
    # support journey never got outreach
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND journey_id IN (SELECT id FROM journeys WHERE account_id='ACC-001' AND product='support')")["n"] == 0
    assert not at.exception, [e.value for e in at.exception]


def test_reset_restores_seed_state():
    at = _at("agent")
    _btn(at, "Run onboarding check").click().run()
    db = at.session_state["db"]
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE origin='session'")["n"] > 0
    at.session_state["_page"] = "overview"
    at.run()
    _btn(at, "Start guided demo").click().run()
    db2 = at.session_state["db"]
    assert db2 is not db and db2.one("SELECT COUNT(*) n FROM interactions WHERE origin='session'")["n"] == 0
