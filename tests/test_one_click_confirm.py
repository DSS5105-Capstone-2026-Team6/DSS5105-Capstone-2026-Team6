"""After any commit, the other open cards are refreshed before drawing, so
their state_version matches the ledger and one Confirm click commits."""

from desk.desk import DispatchDesk


class FakeClient:
    """No LLM needed: the test builds proposals via desk.refresh()."""


def test_stale_cards_refresh_then_confirm_in_one_click(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "ledger.sqlite3"))
    from types import SimpleNamespace
    from desk.contracts import Behaviour, Decision, ParsedRequest
    from app.tabs.desk import worklist as ui_inbox
    from desk.agent import DispatchAgent
    desk = DispatchDesk(audit_path=tmp_path / "audit.sqlite3",
                        agent=DispatchAgent(provider="deepseek", client=FakeClient()))
    open_ids = [o["order_id"] for o in desk.orders.orders
                if o.get("status") not in ("COMPLETE",)][:2]
    stub = lambda oid: Decision(request_id="", behaviour=Behaviour.ALLOCATE,
                                parsed=ParsedRequest(order_id=oid),
                                state_version="old")
    items = [{"msg": "", "decision": desk.refresh(stub(oid))} for oid in open_ids]
    a, b = items
    desk.confirm(a["decision"])                    # bumps the ledger version
    assert b["decision"].state_version != desk.audit.version   # b is stale
    monkeypatch.setattr(ui_inbox, "st", SimpleNamespace(session_state={}))
    done = {open_ids[0]}
    ui_inbox._refresh_stale(items, desk, lambda d: d.parsed.order_id in done)
    assert b["decision"].state_version == desk.audit.version
    rec = desk.confirm(b["decision"])              # first click commits
    assert rec.order_id == open_ids[1]
