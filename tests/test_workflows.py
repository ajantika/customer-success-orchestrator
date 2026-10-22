"""The 15 required workflow checks (rules, tools, state, idempotency). Not a language-quality evaluation."""
import pytest

from cso import evaluation as E
from cso.datagen import build_db
from cso.models import TRANSITIONS, JourneyState, can_transition
from cso.retrieval import get_retriever
from cso.tools import TOOLS, ToolContext, execute_tool, tool_schemas


@pytest.mark.parametrize("cid,name,fn", E.CASES, ids=[f"{c[0]}-{c[1][:40]}" for c in E.CASES])
def test_workflow_case(cid, name, fn):
    ok, detail = fn(build_db())
    assert ok, detail


def test_seed_is_deterministic_and_sized():
    a, b = build_db(), build_db()
    assert a.one("SELECT COUNT(*) n FROM accounts")["n"] == 40
    assert a.q("SELECT id,name,scenario FROM accounts") == b.q("SELECT id,name,scenario FROM accounts")
    assert a.q("SELECT account_id,event_type,ts FROM product_events") == b.q("SELECT account_id,event_type,ts FROM product_events")


def test_terminal_states_have_no_exits_and_transitions_validated():
    assert TRANSITIONS[JourneyState.COMPLETED] == set() and TRANSITIONS[JourneyState.OPTED_OUT] == set()
    assert not can_transition("completed", "monitoring")
    assert can_transition("waiting_for_human", "resolved_awaiting_progress_check")
    assert not can_transition("waiting_for_human", "monitoring")


def test_invalid_tool_input_is_rejected_not_executed():
    db = build_db()
    ctx = ToolContext(db, None, "ACC-001")
    r = execute_tool(ctx, "update_journey_status", {"account_id": "ACC-001", "journey_id": "JRN-001", "new_state": "deleted", "reason": "x" * 5})
    assert not r["ok"] and r["error"]["code"] == "invalid_input"
    r = execute_tool(ctx, "get_setup_progress", {"account_id": "ACC-001", "product": "docs", "sql": "DROP TABLE accounts"})
    assert not r["ok"] and db.one("SELECT COUNT(*) n FROM accounts")["n"] == 40


def test_completion_requires_progress_evidence():
    db = build_db()
    j = db.one("SELECT id FROM journeys WHERE account_id='ACC-001' AND product='docs'")["id"]
    r = execute_tool(ToolContext(db, None, "ACC-001"), "update_journey_status",
                     {"account_id": "ACC-001", "journey_id": j, "new_state": "completed", "reason": "customer says done"})
    assert not r["ok"] and r["error"]["code"] == "completion_not_supported"


def test_every_tool_has_schema_and_boundary():
    names = {s["name"] for s in tool_schemas()}
    assert names == {"get_customer_context", "get_setup_progress", "get_interaction_history", "search_documentation", "check_support_cases",
                     "send_guidance", "pause_journey", "resume_journey", "create_handoff", "update_journey_status"}
    assert all("idempotency_key" not in s["input_schema"]["properties"] for s in tool_schemas())


def test_retrieval_finds_troubleshooting_and_rejects_offtopic():
    r = get_retriever()
    top = r.search("directory integration troubleshooting authentication error timed out", 1)[0]
    assert top["doc_id"] == "DOC-105"
    ctx = ToolContext(build_db(), None, "ACC-001")
    out = execute_tool(ctx, "search_documentation", {"account_id": "ACC-001", "query": "quantum blockchain ledger"})
    assert out["ok"] and not out["data"]["supported"]
