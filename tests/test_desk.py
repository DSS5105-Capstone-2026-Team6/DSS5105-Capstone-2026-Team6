"""Unit tests for the desk layer: state commits, the audit log, the
commit_allocation tool and the v1 routing in desk.router.route.
No network: route() takes the tool log directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.state import DeskState
from desk.audit import AuditLog
from desk.contracts import AllocationRecord, Behaviour, Decision, ParsedRequest
from desk.desk import DispatchDesk
from desk.router import route
from desk.tools import commit_allocation


@pytest.fixture()
def state():
    return DeskState()


@pytest.fixture()
def desk(tmp_path):
    return DispatchDesk(audit_path=tmp_path / "audit.jsonl")


# ---------------- state ----------------

def test_commit_moves_queue_by_priced_work(state):
    before = state.queues["W6"]
    result = state.commit({"category": "ACCESSORIES", "pieces": 600}, "W6")
    b, a = result
    assert b == before
    assert a == pytest.approx(before + 600 / 130 * (1 + 0.5 * 0.05))
    assert state.queues["W6"] == a


def test_commit_rechecks_eligibility(state):
    """Guard: committing to a suspended workshop must fail, state untouched."""
    r = state.commit({"category": "ACCESSORIES", "pieces": 100}, "W7")
    assert "error" in r
    r = state.commit({"category": "TOPS", "pieces": 400}, "W8")   # over cap
    assert "error" in r
    r = state.commit({"category": "TOPS", "pieces": 100}, "W4")   # cannot make
    assert "error" in r


# ---------------- audit ----------------

def test_audit_append_and_load(desk):
    desk.audit.append(AllocationRecord(
        record_id="A-0001", decision_id="R04", order_id="ORD-041",
        workshop_id="W6", pieces=600, committed_by="dispatcher",
        committed_at="2026-04-01T09:00:00", queue_before=1.0, queue_after=5.73))
    records = desk.audit.load_all()
    assert len(records) == 1
    assert records[0].record_id == "A-0001"
    assert records[0].queue_after == pytest.approx(5.73)


# ---------------- commit_allocation tool ----------------

def test_commit_happy_path(desk):
    r = commit_allocation("ORD-041", "Nimble Needle", "test-dispatcher",
                          desk=desk)
    assert r["committed"] is True
    rec = r["record"]
    assert rec["order_id"] == "ORD-041" and rec["workshop_id"] == "W6"
    assert rec["committed_by"] == "test-dispatcher"
    assert rec["queue_before"] == pytest.approx(1.0)
    assert len(desk.audit.load_all()) == 1
    # and the desk's next estimate sees the longer queue
    assert desk.state.queues["W6"] == pytest.approx(rec["queue_after"], abs=1e-2)


def test_commit_failure_cases(desk):
    assert commit_allocation("ORD-999", "W6", desk=desk)["committed"] is False
    assert commit_allocation("ORD-041", "W7", desk=desk)["committed"] is False
    assert commit_allocation("ORD-041", "W6", desk=None)["committed"] is False
    assert desk.audit.load_all() == []        # nothing written on failure
    assert desk.state.queues["W6"] == 1.0     # state untouched


def test_record_ids_increment(desk):
    a = commit_allocation("ORD-041", "W6", desk=desk)["record"]["record_id"]
    b = commit_allocation("ORD-063", "W6", desk=desk)["record"]["record_id"]
    assert (a, b) == ("A-0001", "A-0002")


# ---------------- desk v1 routing ----------------

def _log(entries):
    return [{"tool": t, "arguments": a, "result": r} for t, a, r in entries]


def test_decision_allocate_from_rank(desk):
    log = _log([
        ("lookup_order", {"order_id": "ORD-041"},
         {"status": "found", "matches": [{"order_id": "ORD-041", "pieces": "600",
           "category": "ACCESSORIES", "due_date": "2026-04-21"}]}),
        ("rank_candidates", {"order_id": "ORD-041"},
         {"chosen": "W6", "candidates": [
             {"workshop_id": "W6", "name": "Nimble Needle",
              "estimated_finish": "2026-04-08", "days_late": 0, "cost": 720.0,
              "defect_risk": 0.05, "components": {}}]}),
    ])
    d = route("text", "reply", log)
    assert d.behaviour is Behaviour.ALLOCATE
    assert d.parsed.order_id == "ORD-041"
    assert d.chosen.workshop_id == "W6"
    assert d.explanation == "reply"


def test_decision_ask_on_ambiguous_lookup(desk):
    log = _log([("lookup_order", {"customer": "TrendCart"},
                 {"status": "ambiguous", "matches": [{}, {}, {}]})])
    d = route("t", "r", log)
    assert d.behaviour is Behaviour.ASK


def test_decision_impossible_from_earliest(desk):
    log = _log([("earliest_feasible", {"order_id": "ORD-103"},
                 {"meets_due_single": False, "meets_due_split": False})])
    d = route("t", "r", log)
    assert d.behaviour is Behaviour.IMPOSSIBLE


def test_decision_never_allocates_on_error_results(desk):
    """A rank_candidates call that returned an error must not produce
    ALLOCATE — v1 routing reads results, not tool names."""
    log = _log([("rank_candidates", {"order_id": "ORD-999"},
                 {"error": "unknown order"})])
    d = route("t", "r", log)
    assert d.behaviour is not Behaviour.ALLOCATE
    assert d.chosen is None


def test_confirm_round_trip(desk):
    log = _log([
        ("lookup_order", {"order_id": "ORD-041"},
         {"status": "found", "matches": [{"order_id": "ORD-041", "pieces": "600",
           "category": "ACCESSORIES", "due_date": "2026-04-21"}]}),
        ("rank_candidates", {"order_id": "ORD-041"},
         {"chosen": "W6", "candidates": [
             {"workshop_id": "W6", "name": "Nimble Needle",
              "estimated_finish": "2026-04-08", "days_late": 0, "cost": 720.0,
              "defect_risk": 0.05, "components": {}}]}),
    ])
    d = route("t", "r", log)
    record = desk.confirm(d, committed_by="dispatcher")
    assert record.order_id == "ORD-041" and record.workshop_id == "W6"
    assert record.committed_by == "dispatcher"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
