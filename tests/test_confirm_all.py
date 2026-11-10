"""Batch confirm: every open proposal commits in one go, per-order checks
intact, failures reported without stopping the batch."""

from desk.desk import DispatchDesk


class FakeClient:
    """No LLM needed: proposals are built via desk.refresh()."""


def _proposals(desk, order_ids):
    from desk.contracts import Behaviour, Decision, ParsedRequest
    out = []
    for oid in order_ids:
        stub = Decision(request_id="", behaviour=Behaviour.ALLOCATE,
                        parsed=ParsedRequest(order_id=oid), state_version="old")
        out.append(desk.refresh(stub))
    return out


def _desk(tmp_path):
    from desk.agent import DispatchAgent
    return DispatchDesk(audit_path=tmp_path / "audit.sqlite3",
                        agent=DispatchAgent(provider="deepseek", client=FakeClient()))


def test_confirm_all_commits_every_proposal(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "ledger.sqlite3"))
    desk = _desk(tmp_path)
    open_ids = [o["order_id"] for o in desk.orders.orders
                if o.get("status") != "COMPLETE"][:3]
    results, failures = desk.confirm_all(_proposals(desk, open_ids))
    assert [r.order_id for _, r in results] == open_ids
    assert failures == []
    assert {r.order_id for r in desk.audit.load_all()} == set(open_ids)


def test_confirm_all_reports_failures_without_stopping(tmp_path, monkeypatch):
    # failure case: a proposal with no chosen workshop is refused, the rest
    # still commit
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "ledger.sqlite3"))
    from dataclasses import replace
    desk = _desk(tmp_path)
    open_ids = [o["order_id"] for o in desk.orders.orders
                if o.get("status") != "COMPLETE"][:2]
    broken, good = _proposals(desk, open_ids)
    broken = replace(broken, chosen=None)
    results, failures = desk.confirm_all([broken, good])
    assert [r.order_id for _, r in results] == [open_ids[1]]
    assert failures and failures[0][0] == open_ids[0]


def test_confirm_all_of_already_committed_order_fails_closed(tmp_path, monkeypatch):
    # failure case: committing the same order twice is refused by the ledger
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "ledger.sqlite3"))
    desk = _desk(tmp_path)
    oid = [o["order_id"] for o in desk.orders.orders
           if o.get("status") != "COMPLETE"][0]
    (first,), _ = desk.confirm_all(_proposals(desk, [oid]))
    assert first[1].order_id == oid
    results, failures = desk.confirm_all(_proposals(desk, [oid]))
    assert results == [] and failures
