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


def _btn_starting(at, prefix):
    return next(b for b in at.button if b.label.startswith(prefix))


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
    _btn(at, "Check this customer's setup").click().run()
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
    _btn(at, "Explore setup support").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["guided"] == "onboarding"
    assert _has(at, "Check Maple's setup") and not _has(at, "Check this customer's setup") and not at.exception
    assert any("Maple Design" in m.value for m in at.markdown)


def test_guided_journey_via_clicks_no_duplicates_and_handoff_opens_exact_task():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _btn(at, "Check Maple's setup").click().run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    at.run(); at.run()  # plain reruns send nothing
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    assert at.session_state["acct"] == FEATURED and at.session_state["guided"] == "onboarding"  # selection and walkthrough survive the first action
    assert any("The assistant sent setup guidance to the customer." in m.value for m in at.markdown)  # one short result message
    for reply in ("The directory connection is failing.", "We see an authentication error.", "We already tried those steps."):
        n0 = db.one("SELECT COUNT(*) n FROM interactions WHERE kind='message' AND origin='session' AND account_id=?", (FEATURED,))["n"]
        _btn(at, reply).click().run()                           # the button label is the reply itself
        assert db.one("SELECT COUNT(*) n FROM interactions WHERE kind='message' AND origin='session' AND account_id=?", (FEATURED,))["n"] == n0 + 2  # customer message + assistant response
        assert any(reply in m.value for m in at.markdown), "the new reply must appear in the conversation"
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "waiting_for_human"
    _btn_starting(at, "Open Maple's support task").click().run()  # lands on the queue with Maple's task selected, not another customer's
    assert at.session_state["task"] == tid and at.session_state["acct"] == FEATURED
    assert any("Customer: Maple Design" in m.value for m in at.markdown)
    _btn(at, "Save note and mark resolved").click().run()   # an empty note is refused, with a visible message
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] != "resolved"
    assert any("at least 10 characters" in e.value for e in at.error)   # the error sits beside the field
    next(t for t in at.text_area if t.label == "What was fixed?").set_value("Re-issued the directory token and verified sync.")
    _btn(at, "Save note and mark resolved").click().run()   # one click saves the note and resolves
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"
    _btn(at, "Continue Maple Design's setup").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["prod"] == "docs" and at.session_state["guided"] == "onboarding"
    assert any("Next step: Publish your first document." in c.value for c in at.caption)   # shows the next remaining step
    _btn(at, "Simulate completed setup").click().run()
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "completed"
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND journey_id IN (SELECT id FROM journeys WHERE account_id=? AND product='support')", (FEATURED,))["n"] == 0
    assert not at.exception, [e.value for e in at.exception]


def test_queue_follows_the_selected_customer_not_the_first_task():
    at = _at("agent")
    at.selectbox(key="w_acct").select(FEATURED).run()
    db = at.session_state["db"]
    _btn(at, "Check this customer's setup").click().run()
    for text in ("The directory connection is failing.", "We see an authentication error.", "We already tried those steps."):
        _btn(at, text).click().run()
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    other = db.one("SELECT id FROM human_tasks WHERE origin='seed' AND status!='resolved' ORDER BY priority LIMIT 1")["id"]
    _btn_starting(at, "Open Maple's support task").click().run()
    assert at.session_state["task"] == tid != other
    # entering the queue from the sidebar shows the selected customer's task, never another customer's
    _goto(at, "customer"); _goto(at, "queue")
    assert at.session_state["task"] == tid and at.session_state["acct"] == FEATURED


def test_evaluation_view_stays_after_running_checks():
    at = _at("eval")
    at.radio(key="tab_eval").set_value("System evaluation").run()
    _btn(at, "Run workflow checks").click().run()
    assert at.radio(key="tab_eval").value == "System evaluation"
    assert any("workflow checks" in s.value.lower() for s in at.success), "result message should appear on this view"
    assert not at.exception


def test_restart_resets_only_its_own_walkthrough():
    at = _at("overview")
    _btn(at, "Explore meeting preparation").click().run()
    db = at.session_state["db"]
    _btn(at, "Prepare meeting summary").click().run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE account_id='ACC-041' AND origin='session'")["n"] == 1
    _goto(at, "overview")
    _btn(at, "Explore setup support").click().run()   # starting onboarding must not clear the Northstar recommendation
    _btn(at, "Check Maple's setup").click().run()
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
    _btn(at, "Explore meeting preparation").click().run()
    db = at.session_state["db"]
    assert at.session_state["meeting"] == "MTG-001" and not at.exception
    enrol0 = db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"]
    _btn(at, "Prepare meeting summary").click().run()
    rec = db.one("SELECT * FROM recommendations WHERE meeting_id='MTG-001'")
    assert rec["status"] == "generated" and rec["generation_mode"] == "demo"
    assert any("Review the suggestion before discussing it with the customer" in c.value for c in at.caption)  # message matches the status
    assert rec["talking_point"].startswith("You mentioned wanting to") and "Ask whether" not in rec["talking_point"]
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE meeting_id='MTG-001'")["n"] == 1  # reruns create nothing
    _btn(at, "Mark as reviewed").click().run()
    _btn(at, "Apply an example edit and accept").click().run()
    now = db.one("SELECT * FROM recommendations WHERE meeting_id='MTG-001'")
    assert now["status"] == "accepted" and now["content_original"] != now["content_current"]
    actions = [r["action"] for r in db.q("SELECT action FROM rec_feedback WHERE meeting_id='MTG-001' ORDER BY id")]
    assert actions == ["reviewed", "edited", "accepted"], actions            # acceptance is recorded explicitly
    assert any("Accepted with edits" in m.value for m in at.markdown)
    assert db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"] == enrol0
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 0
    _btn(at, "Mark as discussed").click().run()
    assert any(c.value.startswith("Discussed.") for c in at.caption)        # the review message follows the status
    assert not any("Review the suggestion before discussing" in c.value for c in at.caption)
    _btn(at, "Simulate customer enrollment").click().run()
    assert db.one("SELECT status FROM recommendations WHERE meeting_id='MTG-001'")["status"] == "discussed"
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 1
    assert not at.exception, [e.value for e in at.exception]


def test_typed_completion_claim_without_events_keeps_journey_open():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _btn(at, "Check Maple's setup").click().run()
    at.text_area(key="reply_text").set_value("Setup is now complete.").run()
    _btn(at, "Send message").click().run()
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
    monkeypatch.setattr("cso.ui.agent_page.DEBOUNCE_S", 0)   # a deliberate retry of the same reply is not a double click
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _btn(at, "Check Maple's setup").click().run()
    _btn(at, "The directory connection is failing.").click().run()
    _btn(at, "We see an authentication error.").click().run()
    at.checkbox(key="fault").check().run()          # simulate the ticket system being down
    _btn(at, "We already tried those steps.").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 0
    assert any("could not be created" in m.value for m in at.markdown), "the result message must say the support task was not created"
    assert any("did not go through" in m.value for m in at.markdown), "the customer-facing message must not claim success"
    at.checkbox(key="fault").uncheck().run()        # recover: switch the failure off and retry the same step
    _btn(at, "We already tried those steps.").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    assert not at.exception


def test_walkthroughs_use_plain_language_and_one_primary_action():
    at = _at("overview")
    text = " ".join(m.value for m in at.markdown)
    assert "Help customers get started, resolve problems, and find the right learning support." in text
    assert "Choose a walkthrough below. No login or setup required." in text
    assert any("Interactive demo · Uses sample data and prepared responses." in c.value for c in at.caption)
    assert not any(w in text for w in ("Account Executive", "Solutions Architect", "Account Team", "fictional", "Fictional"))
    _btn(at, "Explore setup support").click().run()
    page = " ".join(m.value for m in at.markdown)
    assert "Maple Design is an example company using the software. Jordan is its administrator" in page
    assert "Choose a customer reply to see how the assistant responds." in page
    assert not any(w in page for w in ("You are replying as the customer", "You are acting as", "Send this reply"))
    assert len([b for b in at.button if b.label == "The directory connection is failing."]) >= 1
    _goto(at, "overview")
    _btn(at, "Explore meeting preparation").click().run()
    page = " ".join(m.value for m in at.markdown)
    assert "You have a conversation with Northstar Retail tomorrow. Review what they want to achieve and the suggested next step." in page
    assert _has(at, "Prepare meeting summary") and not any(w in page for w in ("Account Team", "You are acting as"))
