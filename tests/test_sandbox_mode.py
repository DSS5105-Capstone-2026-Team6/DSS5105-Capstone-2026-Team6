"""Local sandbox mode: a desk built with storage_dir never touches the
shared database — audit, learned performance and API budget all live in
session-local SQLite files (the Streamlit default; the bot is unaffected
and keeps using the shared DB)."""

import sqlite3
from types import SimpleNamespace

from desk.desk import DispatchDesk
from desk.contracts import Behaviour, Decision, ParsedRequest


class FakeClient:
    """No LLM needed: proposals are built via desk.refresh()."""


def _desk(tmp_path, name, **kwargs):
    from desk.agent import DispatchAgent
    return DispatchDesk(agent=DispatchAgent(provider="deepseek",
                                            client=FakeClient()), **kwargs)


def _proposal(desk, oid):
    stub = Decision(request_id="", behaviour=Behaviour.ALLOCATE,
                    parsed=ParsedRequest(order_id=oid), state_version="old")
    return desk.refresh(stub)


def test_sandbox_desk_never_touches_shared_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "shared.sqlite3"))
    from desk.audit import AuditLog
    shared = AuditLog(tmp_path / "shared.sqlite3")   # stands in for the shared ledger

    desk = _desk(tmp_path, "sandbox", storage_dir=tmp_path / "session")
    oid = [o["order_id"] for o in desk.orders.orders
           if o.get("status") != "COMPLETE"][0]
    desk.confirm(_proposal(desk, oid))

    # the sandbox committed locally...
    assert (tmp_path / "session" / "audit.sqlite3").exists()
    assert [r.order_id for r in desk.audit.load_all()] == [oid]
    # ...and the shared ledger never saw it
    assert shared.load_all() == []


def test_sandbox_isolates_performance_and_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "shared.sqlite3"))
    desk = _desk(tmp_path, "sandbox", storage_dir=tmp_path / "session")
    assert desk.agent.budget is not None
    assert desk.agent.budget.database.path != tmp_path / "shared.sqlite3"
    assert desk.performance.database.path != tmp_path / "shared.sqlite3"


def test_default_desk_uses_shared_storage(tmp_path, monkeypatch):
    # failure case for the wiring: without storage_dir the desk must use the
    # shared store (the bot's behaviour), not silently go local
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "shared.sqlite3"))
    desk = _desk(tmp_path, "shared")
    assert desk.audit.database.path == tmp_path / "shared.sqlite3"
    assert desk.agent.budget is None   # budget resolved lazily, shared
