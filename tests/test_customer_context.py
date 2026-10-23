"""Regression tests for the customer-context, navigation and feedback problems found in review.

Each test reproduces a reported failure through real clicks and asserts on stored state and on what the visitor can see.
"""
import json

import pytest

from test_ui import FEATURED, _at, _btn, _goto, _has


def _text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption) + " " + " ".join(i.value for i in at.info)


def _customer_without_tasks(db):
    return db.one("SELECT a.id, a.name FROM accounts a WHERE a.scenario='progressing' AND NOT EXISTS (SELECT 1 FROM human_tasks t WHERE t.account_id=a.id) ORDER BY a.id LIMIT 1")


def _maple_to_handoff(at):
    _btn(at, "Check Maple's setup").click().run()
    for reply in ("The directory connection is failing.", "We see an authentication error.", "We already tried those steps."):
        _btn(at, reply).click().run()


def test_selected_customer_is_consistent_across_pages_and_empty_queue_is_honest():
    at = _at("customer")
    db = at.session_state["db"]
    c = _customer_without_tasks(db)
    at.selectbox(key="w_acct").select(c["id"]).run()
    _goto(at, "agent")
    assert at.session_state["acct"] == c["id"] and at.selectbox(key="w_acct").value == c["id"]
    assert f"Customer: {c['name']}" in _text(at)
    _goto(at, "queue")
    assert at.session_state["acct"] == c["id"]
    assert f"No support tasks for {c['name']}." in _text(at)           # not another customer's task
    assert not at.selectbox                                              # no task from someone else is offered
    _btn(at, "View all support tasks").click().run()                     # showing everyone is an explicit choice
    assert "Showing every customer's support tasks." in _text(at) and at.session_state["queue_scope"] == "all"
    assert at.session_state["acct"] == c["id"]                          # looking at other customers' tasks does not switch the selected customer


def test_support_tasks_default_to_the_selected_customers_own_task():
    at = _at("customer")
    db = at.session_state["db"]
    row = db.one("SELECT t.id tid, t.account_id aid FROM human_tasks t WHERE t.origin='seed' AND t.status!='resolved' ORDER BY t.id DESC LIMIT 1")
    at.selectbox(key="w_acct").select(row["aid"]).run()
    _goto(at, "queue")
    assert at.session_state["task"] == row["tid"] and at.session_state["acct"] == row["aid"]


def test_choosing_another_customer_exits_the_walkthrough_and_keeps_its_progress():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _btn(at, "Check Maple's setup").click().run()
    runs = db.one("SELECT COUNT(*) n FROM agent_runs WHERE account_id=? AND origin='session'", (FEATURED,))["n"]
    other = _customer_without_tasks(db)
    _goto(at, "customer")
    at.selectbox(key="w_acct").select(other["id"]).run()
    assert "guided" not in at.session_state or not at.session_state["guided"]
    _goto(at, "agent")
    assert at.session_state["acct"] == other["id"] and f"Customer: {other['name']}" in _text(at)   # never forced back to Maple
    assert "Guided example" not in _text(at)
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE account_id=? AND origin='session'", (FEATURED,))["n"] == runs   # Maple's progress kept
    _goto(at, "overview")
    assert _has(at, "Continue where you left off")                       # and it can be resumed


def test_exit_walkthrough_button_keeps_customer_and_progress():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    _btn(at, "Check Maple's setup").click().run()
    assert "Guided example: Maple Design." in _text(at)
    _btn(at, "Exit walkthrough").click().run()
    assert "guided" not in at.session_state and at.session_state["acct"] == FEATURED and _has(at, "Check this customer's setup")


def test_reply_stays_visible_and_repeated_escalation_reuses_the_task(monkeypatch):
    monkeypatch.setattr("cso.ui.agent_page.DEBOUNCE_S", 0)
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _maple_to_handoff(at)
    assert "We already tried those steps." in _text(at)                   # the reply and the response are on screen, not only in a toast
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    _btn(at, "Exit walkthrough").click().run()
    n0 = db.one("SELECT COUNT(*) n FROM interactions WHERE actor='customer' AND origin='session'")["n"]
    _btn(at, "We already tried those steps.").click().run()               # a genuinely new message after the task exists
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1   # no second task
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='customer' AND origin='session'")["n"] == n0 + 1   # the message is kept
    ctx = json.loads(db.one("SELECT context FROM human_tasks WHERE id=?", (tid,))["context"])
    assert len(ctx["follow_ups"]) == 1                                    # and attached to the task
    page = _text(at)
    assert f"Support is already working on this issue ({tid}, Maple Design). Setup reminders are paused." in page
    assert _has(at, f"Open support task {tid}")


def test_accidental_double_click_is_not_processed_twice():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _btn(at, "Check Maple's setup").click().run()
    _btn(at, "The directory connection is failing.").click().run()
    n = lambda: db.one("SELECT COUNT(*) n FROM interactions WHERE actor='customer' AND origin='session'")["n"]
    _btn(at, "We see an authentication error.").click().run()
    after_first = n()
    _btn(at, "We see an authentication error.").click().run() if _has(at, "We see an authentication error.") else None
    _btn(at, "Exit walkthrough").click().run()
    _btn(at, "We see an authentication error.").click().run()             # the same reply, clicked again straight away
    assert n() == after_first
    assert "just sent" in _text(at)


def test_resolution_form_validation_resolution_and_return():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _maple_to_handoff(at)
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    _btn(at, "Open the support task").click().run()
    assert "Customer: Maple Design" in _text(at) and at.session_state["task"] == tid
    note = next(t for t in at.text_area if t.label == "What was fixed?")
    # before resolving, going back changes nothing
    _btn(at, "Back to Maple Design's setup").click().run()
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] != "resolved" and at.session_state["acct"] == FEATURED
    _btn(at, "Open support task " + tid).click().run()
    # empty and too-short notes show an error beside the field and keep the text
    _btn(at, "Save note and mark resolved").click().run()
    assert any("at least 10 characters" in e.value for e in at.error)
    next(t for t in at.text_area if t.label == "What was fixed?").set_value("fixed").run()
    _btn(at, "Save note and mark resolved").click().run()
    assert any("at least 10 characters" in e.value for e in at.error)
    assert next(t for t in at.text_area if t.label == "What was fixed?").value == "fixed"   # text preserved
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] != "resolved"
    next(t for t in at.text_area if t.label == "What was fixed?").set_value("Reconnected the employee directory and confirmed it works.")
    _btn(at, "Save note and mark resolved").click().run()
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] == "resolved"
    page = _text(at)
    assert "The support issue for Maple Design is resolved." in page and "Task status: Resolved." in page
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1      # setup rechecked once
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"   # resolving is not completing
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE trigger='progress_check'")["n"] == 1      # reruns add nothing
    _btn(at, "Continue Maple Design's setup").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["prod"] == "docs"
    assert "Next step: Publish your first document." in _text(at)


def test_timeline_shows_conversation_handoff_resolution_and_status_changes():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _maple_to_handoff(at)
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    _btn(at, "Open the support task").click().run()
    next(t for t in at.text_area if t.label == "What was fixed?").set_value("Reconnected the employee directory and confirmed it works.")
    _btn(at, "Save note and mark resolved").click().run()
    _goto(at, "customer")                                                 # no manual refresh needed
    page = _text(at)
    assert "See this customer's messages, support updates, and setup progress in one place." in page
    assert "We already tried those steps." in page                        # customer reply
    assert f"Handoff {tid} created" in page or f"{tid} created" in page  # support-task creation
    assert "Reconnected the employee directory and confirmed it works." in page   # resolution and its note
    assert "Waiting for human" in page or "Waiting for customer" in page  # setup status changes
    assert at.multiselect[0].label == "Show activity from"
    assert list(at.multiselect[0].options) == ["Customer", "Assistant", "Support team", "System"]


def test_empty_timeline_is_a_short_prompt_with_a_working_button():
    at = _at("customer")
    db = at.session_state["db"]
    c = db.one("SELECT a.id, a.name FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM interactions i WHERE i.account_id=a.id) AND EXISTS (SELECT 1 FROM journeys j WHERE j.account_id=a.id) LIMIT 1")
    at.selectbox(key="w_acct").select(c["id"]).run()
    assert f"No activity yet for {c['name']}. Check their setup to begin." in _text(at)
    assert not any("Agent workspace" in m.value for m in at.markdown)
    _btn(at, "Check this customer's setup").click().run()
    assert at.session_state["acct"] == c["id"]
    assert f"Customer: {c['name']}" in _text(at) and _has(at, "Check this customer's setup")


def test_support_result_does_not_appear_on_meeting_preparation():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    _maple_to_handoff(at)
    _btn(at, "Open the support task").click().run()
    next(t for t in at.text_area if t.label == "What was fixed?").set_value("Reconnected the employee directory and confirmed it works.")
    _btn(at, "Save note and mark resolved").click().run()
    _goto(at, "overview")
    _btn(at, "Explore meeting preparation").click().run()
    assert "support issue" not in _text(at).lower() and "Support is already working" not in _text(at)
    _btn(at, "Prepare meeting summary").click().run()
    assert "A suggested next step was prepared" in _text(at) and not at.exception


def test_a_result_about_one_customer_never_appears_under_another():
    at = _at("overview")
    _btn(at, "Explore setup support").click().run()
    db = at.session_state["db"]
    _maple_to_handoff(at)
    _btn(at, "Open the support task").click().run()
    next(t for t in at.text_area if t.label == "What was fixed?").set_value("Reconnected the employee directory and confirmed it works.")
    _btn(at, "Save note and mark resolved").click().run()
    assert "The support issue for Maple Design is resolved." in _text(at)
    other = _customer_without_tasks(db)
    _goto(at, "customer")
    at.selectbox(key="w_acct").select(other["id"]).run()
    _goto(at, "agent")
    assert "Maple Design is resolved" not in _text(at) and "The support issue for Maple" not in _text(at)
    _goto(at, "queue")
    assert "The support issue for Maple" not in _text(at)
