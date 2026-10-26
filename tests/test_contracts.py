"""Unit tests for desk.contracts — every record must round-trip through
JSON, because the audit log and the evaluation both store them that way."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import json

from desk.contracts import (
    AllocationRecord, Behaviour, Candidate, Constraint, Decision,
    ParsedRequest, allocation_from_dict, decision_from_dict, to_dict,
)


def _sample_decision():
    return Decision(
        request_id="R08", behaviour=Behaviour.REFUSE,
        parsed=ParsedRequest(order_id="ORD-073", pieces=400, category="TOPS",
                             suggested_workshop="FreshStart",
                             constraints=[Constraint(kind="exclude",
                                                     originator="Boss",
                                                     target="QuickStitch",
                                                     raw_text="nothing new to QuickStitch")]),
        candidates=[Candidate("W1", "QuickStitch", "2026-04-08", 0.0, 600.0,
                              0.12, {"queue": 4.0, "work": 1.3})],
        explanation="FreshStart cannot take 400 pieces.",
        tool_log=[{"tool": "lookup_order", "arguments": {"order_id": "ORD-073"},
                   "result": {"status": "found"}}],
        created_at="2026-04-01T08:30:00")


def _sample_allocation():
    return AllocationRecord(record_id="A-0001", decision_id="R08",
                            order_id="ORD-073", workshop_id="W6", pieces=400,
                            committed_by="dispatcher", committed_at="2026-04-01T08:35:00",
                            queue_before=1.0, queue_after=4.1)


def test_enum_serialises_as_value():
    assert to_dict(_sample_decision())["behaviour"] == "refuse"


def test_decision_round_trip():
    d = _sample_decision()
    back = decision_from_dict(json.loads(json.dumps(to_dict(d))))
    assert back == d
    assert back.behaviour is Behaviour.REFUSE
    assert back.parsed.constraints[0].originator == "Boss"
    assert back.candidates[0].components == {"queue": 4.0, "work": 1.3}


def test_allocation_round_trip():
    a = _sample_allocation()
    back = allocation_from_dict(json.loads(json.dumps(to_dict(a))))
    assert back == a


def test_all_behaviours_serialise():
    for b in Behaviour:
        d = Decision(request_id="R01", behaviour=b)
        assert json.loads(json.dumps(to_dict(d)))["behaviour"] == b.value


def test_empty_records_use_defaults():
    d = Decision(request_id="R05", behaviour=Behaviour.ASK)
    assert d.candidates == [] and d.tool_log == [] and d.chosen is None
    a = AllocationRecord(record_id="A", decision_id="R05", order_id="ORD-066",
                         workshop_id="W2", pieces=300, committed_by="x",
                         committed_at="t")
    assert a.queue_before == 0.0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
