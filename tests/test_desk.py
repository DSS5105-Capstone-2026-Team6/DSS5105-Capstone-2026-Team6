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


# ---------------- live-queue propagation (Risk 4) ----------------

def test_dispatch_injects_live_queues_into_tools(desk):
    """After a commit, tools called through dispatch_tool must read the
    desk's live chat-side queues, not the 2026-04-01 snapshot."""
    from desk.tools import dispatch_tool
    commit_allocation("ORD-041", "W6", desk=desk)   # 600 pcs onto Nimble Needle
    expected = desk.state.queues["W6"]
    assert expected > 1.0                            # snapshot was 1.0

    q = dispatch_tool("get_queue", {"workshop_ids": ["W6"]}, desk=desk)
    row = q["workshops"][0]
    assert row["queue_days"] == pytest.approx(expected, abs=1e-2)
    assert row["recent_change"] == pytest.approx(expected - 1.0, abs=1e-2)

    rank = dispatch_tool("rank_candidates", {"order_id": "ORD-041"}, desk=desk)
    w6 = next(c for c in rank["candidates"] if c["workshop_id"] == "W6")
    assert w6["components"]["queue_days"] == pytest.approx(expected, abs=1e-2)


def test_dispatch_without_desk_keeps_snapshot():
    """No desk -> fresh stores, tools fall back to the snapshot, and the
    committer refuses (nothing to commit to)."""
    from desk.tools import dispatch_tool
    q = dispatch_tool("get_queue", {"workshop_ids": ["W6"]})
    assert q["workshops"][0]["queue_days"] == 1.0
    assert q["workshops"][0]["recent_change"] == 0.0


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


# ---------------- router v2 ----------------

def _found_lookup(oid, pieces="400", category="TOPS", due="2026-04-20"):
    return ("lookup_order", {"order_id": oid},
            {"status": "found", "matches": [{"order_id": oid, "pieces": pieces,
              "category": category, "due_date": due}]})


def _rank(oid, chosen="W6"):
    return ("rank_candidates", {"order_id": oid},
            {"chosen": chosen, "candidates": [
                {"workshop_id": "W6", "name": "Nimble Needle",
                 "estimated_finish": "2026-04-06", "days_late": 0, "cost": 480.0,
                 "defect_risk": 0.05, "components": {}}]})


def _elig(rows):
    return ("check_eligibility", {"category": "TOPS", "pieces": 400},
            {"category": "TOPS", "pieces": 400, "eligible_count": len(rows),
             "workshops": rows})


def _w(wid, name, eligible, reasons):
    return {"workshop_id": wid, "name": name, "eligible": eligible,
            "reasons": reasons}


def test_refuse_on_ineligible_suggested_workshop(desk):
    """R08: 'send ORD-073 to FreshStart' — FreshStart fails the cap check,
    so the behaviour is REFUSE even though the rank picked an alternative."""
    from desk.register import WorkshopStore
    log = _log([
        _found_lookup("ORD-073"),
        _elig([_w("W8", "FreshStart", False,
                  ["batch of 400 exceeds its 300-piece cap"])]),
        _rank("ORD-073"),
    ])
    d = route("Send ORD-073 (400 hoodies) to FreshStart, their quote was good.",
              "reply", log, workshops=WorkshopStore())
    assert d.behaviour is Behaviour.REFUSE
    assert d.parsed.suggested_workshop == "FreshStart"
    assert d.chosen is None                    # nothing may be committed
    assert len(d.candidates) == 1              # alternatives still listed


def test_exclusion_does_not_trigger_refuse(desk):
    """'not QuickStitch' is a constraint, not a refusal — an exclusion is
    the only reason on the row, so ALLOCATE must stand."""
    from desk.register import WorkshopStore
    log = _log([
        _found_lookup("ORD-053", pieces="300", due="2026-04-10"),
        _elig([_w("W1", "QuickStitch", False, ["excluded by Boss"])]),
        _rank("ORD-053"),
    ])
    d = route("Boss says ORD-053 must not go to QuickStitch.", "reply", log,
              workshops=WorkshopStore())
    assert d.behaviour is Behaviour.ALLOCATE


def test_no_data_when_order_unknown_even_if_model_ranked_another(desk):
    """R18: ORD-999 does not exist. If the model, after the failed lookup,
    ranked a different order anyway, that rank must not produce ALLOCATE."""
    log = _log([
        ("lookup_order", {"order_id": "ORD-999"},
         {"status": "not_found", "matches": []}),
        _rank("ORD-061"),
    ])
    d = route("what's the status of ORD-999?", "reply", log)
    assert d.behaviour is Behaviour.NO_DATA
    assert d.parsed.order_id == "ORD-999"
    assert d.chosen is None


def test_ask_carries_tappable_options(desk):
    """An ambiguous lookup makes the matches tappable choices (journey
    step 6): the UI renders one button per matching order id."""
    log = _log([("lookup_order", {"customer": "TrendCart"},
                 {"status": "ambiguous", "matches": [
                     {"order_id": "ORD-001"}, {"order_id": "ORD-002"},
                     {"order_id": "ORD-003"}]})])
    d = route("the TrendCart order", "reply", log)
    assert d.behaviour is Behaviour.ASK
    assert d.options == ["ORD-001", "ORD-002", "ORD-003"]


def test_no_data_for_history_question_even_with_matches(desk):
    """R02: 'Which workshop did we use last October?' — Harbor Knits orders
    exist, but the question is about history the data doesn't hold."""
    log = _log([("lookup_order", {"customer": "Harbor Knits"},
                 {"status": "ambiguous", "matches": [
                     {"order_id": "ORD-061"}, {"order_id": "ORD-108"}]})])
    d = route("Which workshop did we use for the Harbor Knits batch last "
              "October?", "reply", log)
    assert d.behaviour is Behaviour.NO_DATA
    assert d.options == []


def test_no_data_for_quote_question(desk):
    """R13: 'what price did we quote?' — the order exists (found lookup),
    the quote does not, so this is NO_DATA, not ANSWER."""
    log = _log([("lookup_order", {"order_id": "ORD-120"},
                 {"status": "found", "matches": [{"order_id": "ORD-120",
                  "pieces": "500", "category": "TOPS",
                  "due_date": "2026-04-18"}]})])
    d = route("Finance asks: what price did we quote TrendCart on ORD-120?",
              "reply", log)
    assert d.behaviour is Behaviour.NO_DATA


def test_ambiguous_with_allocate_intent_stays_ask(desk):
    """R03: 'Can we get the TrendCart order moving?' — allocate intent plus
    several matches means ASK, not NO_DATA."""
    log = _log([("lookup_order", {"customer": "TrendCart"},
                 {"status": "ambiguous", "matches": [{"order_id": "ORD-001"}]})])
    d = route("Can we get the TrendCart order moving? They are chasing.",
              "reply", log)
    assert d.behaviour is Behaviour.ASK


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
    d.state_version = desk.audit.version
    record = desk.confirm(d, committed_by="dispatcher")
    assert record.order_id == "ORD-041" and record.workshop_id == "W6"
    assert record.committed_by == "dispatcher"


def test_duplicate_commit_refused(desk):
    """An order is dispatched exactly once: committing it again must not
    double-count the queue. The refusal names the existing record."""
    first = commit_allocation("ORD-041", "W6", desk=desk)
    assert first["committed"] is True
    before = desk.state.queues["W6"]
    second = commit_allocation("ORD-041", "W2", desk=desk)
    assert second["committed"] is False
    assert "already committed" in second["error"] and "A-0001" in second["error"]
    assert desk.state.queues["W6"] == before       # queue untouched
    assert len(desk.audit.load_all()) == 1         # no second record


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
