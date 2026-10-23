"""UI tests with Streamlit's AppTest: pages render, selection survives reruns and navigation, guided demos work through real clicks."""
import pytest
from streamlit.testing.v1 import AppTest

FEATURED = "ACC-001"


def _script(page):
    import streamlit as st
    from cso import session
    from cso.ui import agent_page, config_page, customer, eval_page, nav, overview, queue_page, style, team_page
    mods = {"overview": overview, "customer": customer, "agent": agent_page, "queue": queue_page, "team": team_page, "config": config_page, "eval": eval_page}
    nav.PAGES.update({k: st.Page(m.render, title=k, url_path=k) for k, m in mods.items()})
    style.inject()
    session.get_db()
    target = st.session_state.pop("_goto", None)  # what app.py does via st.switch_page
    if target:
        st.session_state["_page"] = target
    mods[st.session_state.get("_page", page)].render()


def _at(page="overview"):
    at = AppTest.from_function(_script, args=(page,), default_timeout=90)
    at.run()
    return at


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _has(at, label):
    return any(b.label == label for b in at.button)


def _goto(at, page):
    at.session_state["_page"] = page
    at.run()
    return at


@pytest.mark.parametrize("page", ["overview", "customer", "agent", "queue", "team", "config", "eval"])
def test_pages_render_without_exceptions(page):
    at = _at(page)
    assert not at.exception, [e.value for e in at.exception]


def test_selection_survives_actions_and_navigation():
    at = _at("agent")
    at.selectbox(key="w_acct").select(FEATURED).run()
    assert at.session_state["acct"] == FEATURED
    _btn(at, "Run onboarding check").click().run()
    assert at.selectbox(key="w_acct").value == FEATURED and at.radio(key="w_prod").value == "docs" and not at.exception
    for page in ("customer", "queue", "team", "agent", "customer"):  # navigation must not clear the customer
        _goto(at, page)
        assert at.session_state["acct"] in (FEATURED, "ACC-041") and not at.exception
    _goto(at, "agent")
    assert at.selectbox(key="w_acct").value == at.session_state["acct"]


def test_customer_and_agent_pages_show_the_same_customer():
    at = _at("customer")
    at.selectbox(key="w_acct").select(FEATURED).run()
    _goto(at, "agent")
    assert at.selectbox(key="w_acct").value == FEATURED
    _goto(at, "customer")
    assert at.selectbox(key="w_acct").value == FEATURED


def test_guided_demo_opens_maple_agent_workspace():
    at = _at("overview")
    _btn(at, "Start with Maple Design").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["guided"] == "onboarding"
    assert at.selectbox(key="w_acct").value == FEATURED and _has(at, "Run check") and not _has(at, "Run onboarding check")
    assert not at.exception


def test_guided_journey_via_clicks_no_duplicates_and_handoff_opens_exact_task():
    at = _at("overview")
    _btn(at, "Start with Maple Design").click().run()
    db = at.session_state["db"]
    _btn(at, "Run check").click().run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    at.run(); at.run()  # plain reruns send nothing
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    assert at.session_state["acct"] == FEATURED  # selection survives the first action
    for _ in range(3):  # directory failing -> clarifying question; authentication error -> docs; tried steps -> handoff
        _btn(at, "Send reply").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "waiting_for_human"
    _btn(at, "Open handoff").click().run()  # lands on the queue with Maple's task selected, not another customer's
    assert at.session_state["task"] == tid and at.selectbox(key="w_task").value == tid
    assert any("Maple Design" in m.value for m in at.markdown)
    assert _btn(at, "Resolve task").disabled
    next(t for t in at.text_area if t.label.startswith("Resolution note")).set_value("Re-issued the directory token and verified sync.").run()
    _btn(at, "Resolve task").click().run()
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"
    _btn(at, "Return to this customer's journey").click().run()
    assert at.session_state["acct"] == FEATURED and at.selectbox(key="w_acct").value == FEATURED
    _btn(at, "Send reply").click().run()  # setup complete
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "completed"
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND journey_id IN (SELECT id FROM journeys WHERE account_id=? AND product='support')", (FEATURED,))["n"] == 0
    assert not at.exception, [e.value for e in at.exception]


def test_queue_defaults_to_selected_task_not_first():
    at = _at("agent")
    at.selectbox(key="w_acct").select(FEATURED).run()
    db = at.session_state["db"]
    _btn(at, "Run onboarding check").click().run()
    for text in ("The directory connection is failing.", "We see an authentication error.", "We already tried those instructions."):
        _btn(at, text).click().run()
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    _btn(at, f"Open handoff {tid}").click().run()
    other = db.one("SELECT id FROM human_tasks WHERE origin='seed' AND status!='resolved' ORDER BY priority LIMIT 1")["id"]
    assert at.selectbox(key="w_task").value == tid != other


def test_evaluation_view_stays_after_running_checks():
    at = _at("eval")
    at.radio(key="tab_eval").set_value("System evaluation").run()
    _btn(at, "Run workflow checks").click().run()
    assert at.radio(key="tab_eval").value == "System evaluation"
    assert any("workflow checks" in s.value.lower() for s in at.success), "result message should appear on this view"
    assert not at.exception


def test_reset_restores_seed_state():
    at = _at("agent")
    at.selectbox(key="w_acct").select(FEATURED).run()
    _btn(at, "Run onboarding check").click().run()
    db = at.session_state["db"]
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE origin='session'")["n"] > 0
    _goto(at, "overview")
    _btn(at, "Start with Maple Design").click().run()
    db2 = at.session_state["db"]
    assert db2 is not db and db2.one("SELECT COUNT(*) n FROM interactions WHERE origin='session'")["n"] == 0


def test_account_team_guided_flow_and_accept_does_not_enrol():
    at = _at("overview")
    _btn(at, "Start with Northstar Retail").click().run()
    db = at.session_state["db"]
    assert at.session_state["meeting"] == "MTG-001" and not at.exception
    enrol0 = db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"]
    _btn(at, "Prepare brief").click().run()
    rec = db.one("SELECT * FROM recommendations WHERE meeting_id='MTG-001'")
    assert rec["status"] == "generated" and rec["generation_mode"] == "demo"
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE meeting_id='MTG-001'")["n"] == 1  # reruns create nothing
    _btn(at, "Mark reviewed").click().run()
    _btn(at, "Edit and accept").click().run()
    now = db.one("SELECT * FROM recommendations WHERE meeting_id='MTG-001'")
    assert now["status"] == "edited" and now["content_original"] != now["content_current"]
    assert db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"] == enrol0
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 0
    _btn(at, "Mark discussed").click().run()
    _btn(at, "Simulate enrolment").click().run()
    assert db.one("SELECT status FROM recommendations WHERE meeting_id='MTG-001'")["status"] == "discussed"
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 1
    assert not at.exception, [e.value for e in at.exception]
