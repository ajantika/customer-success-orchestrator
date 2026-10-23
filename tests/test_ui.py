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
def test_pages_render_without_exceptions(page, monkeypatch):
    monkeypatch.setenv("CSO_ADVANCED", "1")
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
    _btn(at, "Start customer onboarding").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["guided"] == "onboarding"
    assert _has(at, "Run the check") and not _has(at, "Run onboarding check") and not at.exception
    assert any("Maple Design" in m.value for m in at.markdown)


def test_guided_journey_via_clicks_no_duplicates_and_handoff_opens_exact_task():
    at = _at("overview")
    _btn(at, "Start customer onboarding").click().run()
    db = at.session_state["db"]
    _btn(at, "Run the check").click().run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    at.run(); at.run()  # plain reruns send nothing
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    assert at.session_state["acct"] == FEATURED and at.session_state["guided"] == "onboarding"  # selection and walkthrough survive the first action
    assert any("What just happened" in m.value for m in at.markdown)
    for _ in range(3):  # directory failing -> clarifying question; authentication error -> docs; tried steps -> handoff
        _btn(at, "Send this reply").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "waiting_for_human"
    _btn(at, "Open the support task").click().run()  # lands on the queue with Maple's task selected, not another customer's
    assert at.session_state["task"] == tid and at.selectbox(key="w_task").value == tid
    assert any("Maple Design" in m.value for m in at.markdown)
    _btn(at, "Save note and resolve").click().run()   # an empty note is refused, with a visible message
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] != "resolved"
    assert any("resolution note" in w.value.lower() for w in at.warning)
    next(t for t in at.text_area if t.label.startswith("Resolution note")).set_value("Re-issued the directory token and verified sync.")
    _btn(at, "Save note and resolve").click().run()   # one click saves the note and resolves
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"
    _btn(at, "Return to this customer's journey").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["guided"] == "onboarding"
    _btn(at, "Send this reply").click().run()  # setup complete
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
    _btn(at, f"Open support task {tid}").click().run()
    other = db.one("SELECT id FROM human_tasks WHERE origin='seed' AND status!='resolved' ORDER BY priority LIMIT 1")["id"]
    assert at.selectbox(key="w_task").value == tid != other


def test_evaluation_view_stays_after_running_checks():
    at = _at("eval")
    at.radio(key="tab_eval").set_value("System evaluation").run()
    _btn(at, "Run workflow checks").click().run()
    assert at.radio(key="tab_eval").value == "System evaluation"
    assert any("workflow checks" in s.value.lower() for s in at.success), "result message should appear on this view"
    assert not at.exception


def test_restart_resets_only_its_own_walkthrough():
    at = _at("overview")
    _btn(at, "Start meeting preparation").click().run()
    db = at.session_state["db"]
    _btn(at, "Prepare the brief").click().run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE account_id='ACC-041' AND origin='session'")["n"] == 1
    _goto(at, "overview")
    _btn(at, "Start customer onboarding").click().run()   # starting onboarding must not clear the Northstar recommendation
    _btn(at, "Run the check").click().run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE account_id='ACC-041' AND origin='session'")["n"] == 1
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE account_id='ACC-001' AND origin='session'")["n"] == 1
    _goto(at, "overview")
    assert _has(at, "Continue where you left off") and _has(at, "Start over")
    next(b for b in at.button if b.key == "go_onboarding").click().run()  # Start over for Maple only
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE account_id='ACC-001' AND origin='session'")["n"] == 0
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE account_id='ACC-041' AND origin='session'")["n"] == 1
    assert not at.exception


def test_account_team_guided_flow_and_accept_does_not_enrol():
    at = _at("overview")
    _btn(at, "Start meeting preparation").click().run()
    db = at.session_state["db"]
    assert at.session_state["meeting"] == "MTG-001" and not at.exception
    enrol0 = db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"]
    _btn(at, "Prepare the brief").click().run()
    rec = db.one("SELECT * FROM recommendations WHERE meeting_id='MTG-001'")
    assert rec["status"] == "generated" and rec["generation_mode"] == "demo"
    assert any("Review required" in c.value for c in at.caption)           # message matches the status
    assert rec["talking_point"].startswith("You mentioned wanting to") and "Ask whether" not in rec["talking_point"]
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE meeting_id='MTG-001'")["n"] == 1  # reruns create nothing
    _btn(at, "Mark as reviewed").click().run()
    _btn(at, "Apply example edit and accept").click().run()
    now = db.one("SELECT * FROM recommendations WHERE meeting_id='MTG-001'")
    assert now["status"] == "accepted" and now["content_original"] != now["content_current"]
    actions = [r["action"] for r in db.q("SELECT action FROM rec_feedback WHERE meeting_id='MTG-001' ORDER BY id")]
    assert actions == ["reviewed", "edited", "accepted"], actions            # acceptance is recorded explicitly
    assert any("Accepted with edits" in m.value for m in at.markdown)
    assert db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"] == enrol0
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 0
    _btn(at, "Mark as discussed").click().run()
    assert any(c.value.startswith("Discussed.") for c in at.caption)        # "Review required" no longer shown
    assert not any("Review required" in c.value for c in at.caption)
    _btn(at, "Simulate enrolment").click().run()
    assert db.one("SELECT status FROM recommendations WHERE meeting_id='MTG-001'")["status"] == "discussed"
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 1
    assert not at.exception, [e.value for e in at.exception]


def test_typed_completion_claim_without_events_keeps_journey_open():
    at = _at("overview")
    _btn(at, "Start customer onboarding").click().run()
    db = at.session_state["db"]
    _btn(at, "Run the check").click().run()
    at.text_area(key="reply_text").set_value("Setup is now complete.").run()
    _btn(at, "Send as the customer").click().run()
    state = db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"]
    assert state != "completed" and db.one("SELECT COUNT(*) n FROM product_events WHERE account_id=? AND origin='session' AND event_type!='usage_session'", (FEATURED,))["n"] == 0
    last = db.one("SELECT body FROM interactions WHERE actor='agent' AND kind='message' AND account_id=? ORDER BY rid DESC LIMIT 1", (FEATURED,))["body"]
    assert "don't see" in last


def test_default_view_hides_reviewer_only_features(monkeypatch):
    monkeypatch.delenv("CSO_ADVANCED", raising=False)
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception
    assert not any("AI model" in e.label for e in at.sidebar.expander)
    assert not any(b.label.startswith("+") for b in at.sidebar.button)
    team = _at("team")
    assert not any(b.label == "Apply situation" for b in team.button)


def test_failed_handoff_is_reported_honestly_and_can_be_retried(monkeypatch):
    monkeypatch.setenv("CSO_ADVANCED", "1")
    at = _at("overview")
    _btn(at, "Start customer onboarding").click().run()
    db = at.session_state["db"]
    _btn(at, "Run the check").click().run()
    _btn(at, "Send this reply").click().run()
    _btn(at, "Send this reply").click().run()
    at.checkbox(key="fault").check().run()          # simulate the ticket system being down
    _btn(at, "Send this reply").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 0
    assert any("Handoff FAILED" in m.value and "nothing was created" in m.value for m in at.markdown), "the card must say the handoff failed"
    assert any("did not go through" in m.value for m in at.markdown), "the customer-facing message must not claim success"
    at.checkbox(key="fault").uncheck().run()        # recover: switch the failure off and retry the same step
    _btn(at, "Send this reply").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    assert not at.exception


def test_every_walkthrough_screen_has_a_role_label_and_next_action():
    at = _at("overview")
    _btn(at, "Start customer onboarding").click().run()
    assert any(m.value.startswith('<div class="cso-role">You are') for m in at.markdown)
    _goto(at, "overview")
    _btn(at, "Start meeting preparation").click().run()
    assert any(m.value.startswith('<div class="cso-role">You are acting as the Account Team') for m in at.markdown)
    assert _has(at, "Prepare the brief")
