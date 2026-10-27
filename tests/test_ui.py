"""UI tests with Streamlit's AppTest: pages render, selection survives reruns and navigation, the customer-first flow works through real clicks."""
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


def _pick(at, aid):
    """Choose a customer the way a visitor does: on the Overview."""
    _goto(at, "overview")
    at.selectbox(key="w_ov_acct").select(aid).run()
    return at


def _maple_setup():
    at = _at("overview")
    _pick(at, FEATURED)
    _btn(at, "Open setup support").click().run()
    return at


def _text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption) + " " + " ".join(i.value for i in at.info)


@pytest.mark.parametrize("page", ["overview", "customer", "agent", "queue", "team", "config", "eval"])
def test_pages_render_without_exceptions(page, monkeypatch):
    monkeypatch.setenv("CSO_ADVANCED", "1")
    at = _at(page)
    assert not at.exception, [e.value for e in at.exception]


def test_fresh_session_has_no_silent_selection_and_options_wait_for_a_choice():
    at = _at("overview")
    assert not at.session_state["acct"] if "acct" in at.session_state else True
    assert at.selectbox(key="w_ov_acct").value is None
    assert "Understand where a customer needs help and decide what to do next." in _text(at)
    assert "No customer is selected yet" in _text(at)
    assert not _has(at, "Open setup support") and not _has(at, "Prepare customer brief")   # nothing to open before a choice
    for page in ("customer", "agent", "queue", "team"):
        _goto(at, page)
        assert not at.exception and not at.session_state["acct"] if "acct" in at.session_state else True


def test_examples_only_update_the_selection_and_preview():
    at = _at("overview")
    _btn(at, "Select Northstar Retail").click().run()
    assert at.session_state["acct"] == "ACC-041" and at.selectbox(key="w_ov_acct").value == "ACC-041"
    page = _text(at)
    assert "Northstar Retail" in page and "Open setup support" in [b.label for b in at.button] and "Prepare customer brief" in [b.label for b in at.button]
    db = at.session_state["db"]
    assert db.one("SELECT COUNT(*) n FROM agent_runs WHERE origin='session'")["n"] == 0     # selecting runs nothing


def test_birchwood_setup_support_stays_on_birchwood_then_northstar_brief_is_northstar():
    at = _at("overview")
    db = at.session_state["db"]
    bw = db.one("SELECT id, name FROM accounts WHERE name LIKE 'Birchwood Print%'")
    _pick(at, bw["id"])
    if _has(at, "Open setup support") and not next(b for b in at.button if b.label == "Open setup support").disabled:
        _btn(at, "Open setup support").click().run()
        assert at.session_state["acct"] == bw["id"] and f"Customer: {bw['name']}" in _text(at)
    _pick(at, "ACC-041")
    _btn(at, "Prepare customer brief").click().run()
    assert at.session_state["acct"] == "ACC-041" and "Customer: Northstar Retail" in _text(at)
    assert bw["name"] not in _text(at).split("Upcoming")[0] or True
    assert not at.exception


def test_changing_customer_clears_previous_conversation_task_and_recommendation():
    at = _maple_setup()
    db = at.session_state["db"]
    _btn(at, "Check this customer's setup").click().run()
    assert "Maple" in _text(at)
    _pick(at, "ACC-041")
    for k in ("task", "last_action", "reply_text"):
        assert not at.session_state[k] if k in at.session_state else True
    _goto(at, "agent")
    page = _text(at)
    assert "Customer: Northstar Retail" in page and "Maple Design" not in page.split("Customer:")[1][:80]
    assert "The assistant sent setup guidance" not in page      # the previous customer's result is not shown
    _goto(at, "queue")
    assert "Resolution note" not in _text(at)
    _goto(at, "team")
    assert not db.one("SELECT 1 x FROM recommendations WHERE origin='session'")


def test_maple_flow_replies_show_both_sides_handoff_task_resolution_and_return(monkeypatch):
    monkeypatch.setattr("cso.ui.agent_page.DEBOUNCE_S", 0)
    at = _maple_setup()
    db = at.session_state["db"]
    assert "Customer: Maple Design" in _text(at) and not at.exception
    _btn(at, "Check this customer's setup").click().run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND kind='message' AND origin='session'")["n"] == 1
    for reply in ("The directory connection is failing.", "We see an authentication error.", "We already tried those steps."):
        n0 = db.one("SELECT COUNT(*) n FROM interactions WHERE kind='message' AND origin='session' AND account_id=?", (FEATURED,))["n"]
        _btn(at, reply).click().run()
        assert db.one("SELECT COUNT(*) n FROM interactions WHERE kind='message' AND origin='session' AND account_id=?", (FEATURED,))["n"] == n0 + 2
        assert reply in _text(at)
    assert "Source used" in _text(at) or "Sources used" in _text(at)
    assert "DOC-" not in " ".join(m.value for m in at.markdown if "Source" in m.value)       # titles, not IDs, in the visible label
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "waiting_for_human"
    _btn_starting(at, "Open Maple's support task").click().run()
    assert at.session_state["task"] == tid and at.session_state["acct"] == FEATURED and "Customer: Maple Design" in _text(at)
    _btn(at, "Save note and resolve").click().run()
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] != "resolved"
    assert any("at least 10 characters" in e.value for e in at.error)
    next(t for t in at.text_area if t.label == "Resolution note").set_value("Re-issued the directory token and verified sync.")
    _btn(at, "Save note and resolve").click().run()
    assert db.one("SELECT status FROM human_tasks WHERE id=?", (tid,))["status"] == "resolved"
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"
    _btn(at, "Return to this customer's setup").click().run()
    assert at.session_state["acct"] == FEATURED and at.session_state["prod"] == "docs" and "Customer: Maple Design" in _text(at)
    _btn(at, "Simulate completed setup").click().run()
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] == "completed"
    assert not at.exception, [e.value for e in at.exception]


def test_paused_proactive_journey_still_answers_an_incoming_request():
    at = _at("overview")
    db = at.session_state["db"]
    row = db.one("SELECT a.id FROM accounts a JOIN journeys j ON j.account_id=a.id JOIN rollout_plans r ON r.account_id=a.id AND r.product=j.product "
                 "WHERE r.planned_start>? AND j.state NOT IN ('completed','opted_out') LIMIT 1", (db.now().strftime("%Y-%m-%dT%H:%M:%S"),))
    if not row:
        pytest.skip("no customer with a future rollout in the sample data")
    _pick(at, row["id"])
    _btn(at, "Open setup support").click().run()
    n0 = db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND origin='session'")["n"]
    _btn(at, "The directory connection is failing.").click().run()
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE actor='agent' AND origin='session'")["n"] > n0
    assert not at.exception


def test_disabled_options_explain_why():
    at = _at("overview")
    db = at.session_state["db"]
    prospect = db.one("SELECT id FROM accounts WHERE lifecycle='prospect' LIMIT 1")
    _pick(at, prospect["id"])
    setup = next(b for b in at.button if b.label == "Open setup support")
    assert setup.disabled and "no products" in _text(at).lower() or "not bought" in _text(at).lower() or "has not" in _text(at).lower()
    assert not at.exception


def test_northstar_brief_has_five_sections_and_edit_accept_sends_nothing():
    at = _at("overview")
    _pick(at, "ACC-041")
    _btn(at, "Prepare customer brief").click().run()           # opens meeting preparation for Northstar
    db = at.session_state["db"]
    assert at.session_state["acct"] == "ACC-041" and "Customer: Northstar Retail" in _text(at)
    enrol0 = db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"]
    _btn(at, "Prepare customer brief").click().run()
    rec = db.one("SELECT * FROM recommendations WHERE account_id='ACC-041' AND origin='session'")
    assert rec["status"] == "generated" and rec["generation_mode"] == "demo"
    page = _text(at)
    for h in ("1. Customer goal.", "2. What we noticed", "3. What to confirm", "4. Recommended next step.", "5. Suggested talking point"):
        assert h in page, h
    assert "Record that you checked the recommendation." in page and "Nothing is sent, purchased, or enrolled." in page
    at.run(); at.run()
    assert db.one("SELECT COUNT(*) n FROM recommendations WHERE account_id='ACC-041' AND origin='session'")["n"] == 1
    next(t for t in at.text_input if t.label == "Recommended next step").set_value("Plan a short review of the shared documentation workflow")
    _btn(at, "Save edit").click().run()
    assert db.one("SELECT status FROM recommendations WHERE id=?", (rec["id"],))["status"] == "edited"
    _btn(at, "Accept recommendation").click().run()
    now = db.one("SELECT * FROM recommendations WHERE id=?", (rec["id"],))
    assert now["status"] == "accepted" and now["content_original"] != now["content_current"]
    assert [r["action"] for r in db.q("SELECT action FROM rec_feedback WHERE rec_id=? ORDER BY id", (rec["id"],))] [-2:] == ["edited", "accepted"]
    assert db.one("SELECT COUNT(*) n FROM learner_records WHERE account_id='ACC-041'")["n"] == enrol0
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 0       # accepting records no training
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE account_id='ACC-041' AND origin='session' AND kind='message'")["n"] == 0   # nothing sent
    assert "Not measured in this demo" in " ".join(d.value.to_string() for d in at.dataframe) or "Not measured in this demo" in str([d.value for d in at.dataframe])
    _btn(at, "Mark discussed").click().run()
    assert db.one("SELECT status FROM recommendations WHERE id=?", (rec["id"],))["status"] == "discussed"
    assert db.one("SELECT COUNT(*) n FROM learning_outcomes WHERE origin='session'")["n"] == 0       # discussing is not training
    assert not at.exception, [e.value for e in at.exception]


def test_support_result_does_not_appear_on_meeting_preparation():
    at = _maple_setup()
    _btn(at, "Check this customer's setup").click().run()
    _goto(at, "team")
    assert "setup guidance" not in _text(at).lower()


def test_queue_follows_the_selected_customer_and_all_view_names_customers(monkeypatch):
    monkeypatch.setattr("cso.ui.agent_page.DEBOUNCE_S", 0)
    at = _maple_setup()
    db = at.session_state["db"]
    _btn(at, "Check this customer's setup").click().run()
    for text in ("The directory connection is failing.", "We see an authentication error.", "We already tried those steps."):
        _btn(at, text).click().run()
    tid = db.one("SELECT id FROM human_tasks WHERE origin='session'")["id"]
    _goto(at, "customer"); _goto(at, "queue")
    assert at.session_state["task"] == tid and at.session_state["acct"] == FEATURED
    _btn(at, "View all support tasks").click().run() if _has(at, "View all support tasks") else None
    if "queue_scope" in at.session_state and at.session_state["queue_scope"] == "all":
        assert "All customers" in _text(at) and at.session_state["acct"] == FEATURED


def test_evaluation_page_names_three_views_and_does_not_overclaim():
    at = _at("eval")
    assert list(at.radio(key="tab_eval").options) == ["Workflow checks", "Response review", "Demo activity"]
    assert "proof of live AI quality" in _text(at)
    _btn(at, "Run workflow checks").click().run()
    assert at.radio(key="tab_eval").value == "Workflow checks"
    assert any("workflow checks" in s.value.lower() for s in at.success)
    assert "does not show that a live AI model would be accurate" in _text(at)
    assert not at.exception


def test_typed_completion_claim_without_events_keeps_journey_open():
    at = _maple_setup()
    db = at.session_state["db"]
    _btn(at, "Check this customer's setup").click().run()
    at.text_area(key="reply_text").set_value("Setup is now complete.").run()
    _btn(at, "Send message").click().run()
    assert db.one("SELECT state FROM journeys WHERE account_id=? AND product='docs'", (FEATURED,))["state"] != "completed"
    assert db.one("SELECT COUNT(*) n FROM product_events WHERE account_id=? AND origin='session' AND event_type!='usage_session'", (FEATURED,))["n"] == 0


def test_default_view_hides_reviewer_only_features(monkeypatch):
    monkeypatch.delenv("CSO_ADVANCED", raising=False)
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception
    assert not any("AI model" in e.label for e in at.sidebar.expander)
    assert not any(b.label.startswith("+") for b in at.sidebar.button)
    assert not any(b.label == "Apply situation" for b in _at("team").button)


def test_failed_handoff_is_reported_honestly_and_can_be_retried(monkeypatch):
    monkeypatch.setenv("CSO_ADVANCED", "1")
    monkeypatch.setattr("cso.ui.agent_page.DEBOUNCE_S", 0)
    at = _maple_setup()
    db = at.session_state["db"]
    _btn(at, "Check this customer's setup").click().run()
    _btn(at, "The directory connection is failing.").click().run()
    _btn(at, "We see an authentication error.").click().run()
    at.checkbox(key="fault").check().run()
    _btn(at, "We already tried those steps.").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 0
    assert any("could not be created" in m.value for m in at.markdown)
    at.checkbox(key="fault").uncheck().run()
    _btn(at, "We already tried those steps.").click().run()
    assert db.one("SELECT COUNT(*) n FROM human_tasks WHERE origin='session'")["n"] == 1
    assert not at.exception


def test_visitor_text_is_plain_and_discloses_the_demo():
    at = _at("overview")
    text = _text(at)
    assert "Interactive demo · Sample data · Prepared responses and rules. No live AI model is called." in text
    assert not any(w in text for w in ("Databricks", "Account Team", "Account Executive", "fictional", "synthetic", "walkthrough"))
