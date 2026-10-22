"""Live AI adapter tests with a fake provider client (no network, no API key).

These verify the tool-use loop wiring and error handling only. They say nothing about real model quality.
"""
from types import SimpleNamespace

import anthropic
import httpx

from cso import services as S
from cso.datagen import build_db


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


def _resp(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


def _tool(i, name, **inp):
    return _resp(Block(type="text", text=f"Calling {name}."), Block(type="tool_use", id=f"tu{i}", name=name, input=inp))


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patch(monkeypatch, client):
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key=None: client)


def test_live_loop_executes_tools_and_feeds_results_back(monkeypatch):
    db = build_db()
    j = db.one("SELECT id FROM journeys WHERE account_id='ACC-001' AND product='docs'")["id"]
    c = FakeClient([_tool(1, "get_customer_context", account_id="ACC-001", journey_id=j),
                    _tool(2, "get_setup_progress", account_id="ACC-001", product="docs"),
                    _resp(Block(type="text", text="Not stalled yet, so no message."), stop="end_turn")])
    _patch(monkeypatch, c)
    r = S.run_onboarding_check(db, "ACC-001", j, "live", {"api_key": "test", "model": "fake"})
    assert r["outcome"] == "completed" and r["steps"] == 2 and "Not stalled" in r["summary"]
    last = c.calls[-1]["messages"][-2]  # the list is shared, so the final assistant turn sits after the last tool_result
    assert last["content"][0]["type"] == "tool_result" and last["content"][0]["tool_use_id"] == "tu2"
    assert db.one("SELECT mode FROM agent_runs ORDER BY id DESC LIMIT 1")["mode"] == "live"


def test_live_model_cannot_cross_accounts_or_bypass_rules(monkeypatch):
    db = build_db()
    j = db.one("SELECT id FROM journeys WHERE account_id='ACC-001' AND product='docs'")["id"]
    other = db.one("SELECT id FROM accounts WHERE scenario='not_started' LIMIT 1")["id"]
    c = FakeClient([_tool(1, "get_setup_progress", account_id=other, product="docs"),
                    _resp(Block(type="text", text="done"), stop="end_turn")])
    _patch(monkeypatch, c)
    S.run_onboarding_check(db, "ACC-001", j, "live", {"api_key": "test"})
    row = db.one("SELECT ok, error FROM tool_executions ORDER BY rid DESC LIMIT 1")
    assert row["ok"] == 0 and row["error"] == "account_boundary"


def test_live_failure_is_reported_not_replaced_by_scripted_output(monkeypatch):
    db = build_db()
    j = db.one("SELECT id FROM journeys WHERE account_id='ACC-001' AND product='docs'")["id"]
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
    _patch(monkeypatch, FakeClient([err]))
    r = S.run_onboarding_check(db, "ACC-001", j, "live", {"api_key": "test"})
    assert r["outcome"] == "error" and "Could not reach" in r["error"]
    assert db.one("SELECT COUNT(*) n FROM interactions WHERE origin='session'")["n"] == 0
    assert db.one("SELECT state FROM journeys WHERE id=?", (j,))["state"] == "monitoring"


def test_step_limit_stops_the_loop(monkeypatch):
    db = build_db()
    j = db.one("SELECT id FROM journeys WHERE account_id='ACC-001' AND product='docs'")["id"]
    loops = [_tool(i, "get_setup_progress", account_id="ACC-001", product="docs") for i in range(20)]
    _patch(monkeypatch, FakeClient(loops))
    from cso.agent import run_agent
    r = run_agent(db, "ACC-001", j, {"type": "onboarding_check", "ref": "x"}, "live", {"api_key": "t"}, max_steps=3)
    assert r["outcome"] == "step_limit" and r["steps"] == 3
