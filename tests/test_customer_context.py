"""Customer-context, navigation and feedback regressions, reproduced through real clicks.

Each test asserts on stored state and on what the visitor can see.
"""
import json

from test_ui import FEATURED, _at, _btn, _btn_starting, _goto, _has, _maple_setup, _pick, _text


def _customer_without_tasks(db):
    return db.one("SELECT a.id, a.name FROM accounts a WHERE a.scenario='progressing' AND NOT EXISTS (SELECT 1 FROM human_tasks t WHERE t.account_id=a.id) ORDER BY a.id LIMIT 1")


def _maple_to_handoff(at):
    _btn(at, "Check this customer's setup").click().run()
    for reply in ("The directory connection is failing.", "We see an authentication error.", "We already tried those steps."):
        _btn(at, reply).click().run()


def _resolve(at, note="Reconnected the employee directory and confirmed it works."):
    _btn_starting(at, "Open Maple's support task").click().run()
    next(t for t in at.text_area if t.label == "Resolution note").set_value(note)
    _btn(at, "Save note and resolve").click().run()


def test_selected_customer_is_consistent_across_pages_and_empty_queue_is_honest():
    at = _at("overview")
    c = _customer_without_tasks(at.session_state["db"])
    _pick(at, c["id"])
    _goto(at, "agent")
    assert at.session_state["acct"] == c["id"] and at.selectbox(key="w_acct").value == c["id"]
    assert f"Customer: {c['name']}" in _text(at) and "Viewing as: Customer Success" in _text(at)
    _goto(at, "queue")
    assert f"No support tasks for {c['name']}." in _text(at) and not at.selectbox
    _btn(at, "View all support tasks").click().run()
    assert "All customers." in _text(at) and at.session_state["acct"] == c["id"]      # viewing everyone does not switch the customer


def test_support_tasks_default_to_the_selected_customers_own_task():
    at = _at("overview")
    row = at.session_state["db"].one("SELECT t.id tid, t.account_id aid FROM human_tasks t WHERE t.origin='seed' AND t.status!='resolved' ORDER BY t.id DESC LIMIT 1")
    _pick(at, row["aid"])
    _goto(at, "queue")
    assert at.session_state["task"] == row["tid"] and at.session_state["acct"] == row["aid"]


def test_reply_stays_visible_and_repeated_escalation_reuses_the_task(monkeypatch):
    monkeypatch.setattr("cso.ui.agent_page.DEBOUNCE_S", 0)
    at = _maple_setup()
    db = at.session_state["db"]
    _maple_to_handoff(at)
    assert "We already tried those steps." in _text(at)
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    n0 = db.one("SELECT COUNT(*) n FROM interactions WHERE actor='customer' AND origin='session'")["n"]
    _btn(at, "We already tried those steps.").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='customer' AND origin='session'")["n"] == n0 + 1
    assert len(json.loads(db.one("SELECT context FROM human_tasks WHERE id=?", (tid,))["context"])["follow_ups"]) == 1
    opens = [b.label for b in at.button if b.label.startswith("Open Maple's support task")]
    assert opens == [f"Open Maple's support task · {tid}"]


def test_accidental_double_click_is_not_processed_twice():
    at = _maple_setup()
    db = at.session_state["db"]
    _btn(at, "Check this customer's setup").click().run()
    _btn(at, "We see an authentication error.").click().run()
    n = lambda: db.one("SELECT COUNT(*) n FROM interactions WHERE actor='customer' AND origin='session'")["n"]
    first = n()
    _btn(at, "We see an authentication error.").click().run()
    assert n() == first and "just sent" in _text(at)


def test_resolution_form_validation_resolution_and_return():
    at = _maple_setup()
    db = at.session_state["db"]
    _maple_to_handoff(at)
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    _btn_starting(at, "Open Maple's support task").click().run()
    page = _text(at)
    assert "Describe what you fixed, what you checked, and what the customer should do next." in page
    assert "Close this support task and record the resolution. This does not automatically mean the customer has finished setup." in page
    _btn(at, "Return to this customer's setup").click().run()                       # leaving changes nothing
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] != "resolved" and at.session_state["acct"] == FEATURED
    _btn_starting(at, "Open Maple's support task").click().run()
    _btn(at, "Save note and resolve").click().run()
    assert any("at least 10 characters" in e.value for e in at.error)
    next(t for t in at.text_area if t.label == "Resolution note").set_value("fixed").run()
    _btn(at, "Save note and resolve").click().run()
    assert any("at least 10 characters" in e.value for e in at.error)
    assert next(t for t in at.text_area if t.label == "Resolution note").value == "fixed"
    next(t for t in at.text_area if t.label == "Resolution note").set_value("Reconnected the employee directory and confirmed it works.")
    _btn(at, "Save note and resolve").click().run()
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] == "resolved"
    assert "Task status: Resolved." in _text(at)
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1
    _btn(at, "Return to this customer's setup").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["prod"] == "docs"
    assert "Next step: Publish your first document." in _text(at)


def test_timeline_shows_conversation_handoff_resolution_and_status_changes():
    at = _maple_setup()
    _maple_to_handoff(at)
    _resolve(at)
    _goto(at, "customer")
    page = _text(at)
    assert "See this customer's messages, support updates, and setup progress in one place." in page
    assert "We already tried those steps." in page
    assert "Reconnected the employee directory and confirmed it works." in page
    assert at.multiselect[0].label == "Show activity from" and list(at.multiselect[0].options) == ["Customer", "Assistant", "Support team", "System"]


def test_empty_timeline_is_a_short_prompt_with_a_working_button():
    at = _at("overview")
    db = at.session_state["db"]
    c = db.one("SELECT a.id, a.name FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM interactions i WHERE i.account_id=a.id) AND EXISTS (SELECT 1 FROM journeys j WHERE j.account_id=a.id) LIMIT 1")
    _pick(at, c["id"])
    _goto(at, "customer")
    assert f"No activity yet for {c['name']}. Check their setup to begin." in _text(at)
    _btn(at, "Check this customer's setup").click().run()
    assert at.session_state["acct"] == c["id"] and f"Customer: {c['name']}" in _text(at)


def test_a_result_about_one_customer_never_appears_under_another():
    at = _maple_setup()
    _maple_to_handoff(at)
    _resolve(at)
    assert "The support issue for Maple Design is resolved." in _text(at)
    other = _customer_without_tasks(at.session_state["db"])
    _pick(at, other["id"])
    for page in ("agent", "queue", "team", "customer"):
        _goto(at, page)
        assert "Maple" not in _text(at).replace("Maple Design", "Maple Design") or f"Customer: {other['name']}" in _text(at)
        assert "The support issue for Maple" not in _text(at) and "Reconnected the employee directory" not in _text(at)


def test_customer_without_products_shows_a_clear_message_not_blank_sections():
    at = _at("overview")
    prospect = at.session_state["db"].one("SELECT id, name FROM accounts WHERE lifecycle='prospect' LIMIT 1")
    _pick(at, prospect["id"])
    _goto(at, "customer")
    assert f"{prospect['name']} is still evaluating the product and has not bought anything yet" in _text(at)
    assert not _has(at, "Check this customer's setup") and not at.exception
    _pick(at, FEATURED)
    _goto(at, "customer")
    page = _text(at)
    assert "Rollout started" in page or "Rollout planned for" in page
    assert "Recent usage:" in page and "Products and setup progress" in page


def test_customer_workspace_explains_the_decision_in_plain_language():
    at = _at("overview")
    _pick(at, FEATURED)
    _goto(at, "customer")
    page = _text(at)
    assert "Suggested next step and why" in page
    assert "Customer goal." in page and "Open support issues" in page
    assert "❌" not in page and "✗" not in page
    assert any(e.label == "Why this decision?" for e in at.expander)
