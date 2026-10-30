"""Split orders in the chat layer: an IMPOSSIBLE reached through
earliest_feasible alone still gets candidates, a faster two-workshop split
is offered, and confirm_split commits both parts in one transaction.
The simulator is untouched (it still sends one batch to one workshop)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.contracts import Behaviour, decision_from_dict, to_dict
from desk.desk import DispatchDesk, ProposalChanged
from desk.tools import commit_allocation, dispatch_tool, earliest_feasible


class FeasibilityAgent:
    """Calls lookup_order + earliest_feasible only, like the H14 run."""

    def __init__(self, order_id="ORD-029"):
        from desk.register import WorkshopStore
        self.workshops = WorkshopStore()
        self.history, self.tool_log = [], []
        self.order_id = order_id

    def chat(self, text, verbose=False):
        self.tool_log = []
        for name, args in (("lookup_order", {"order_id": self.order_id}),
                           ("earliest_feasible", {"order_id": self.order_id})):
            self.tool_log.append({"tool": name, "arguments": args,
                                  "result": dispatch_tool(name, args, desk=self.desk)})
        return "It cannot make the date; SteadyHands (W2) is earliest."


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "runtime.sqlite3"))
    return DispatchDesk(agent=FeasibilityAgent(), audit_path=tmp_path / "audit.jsonl")


def test_impossible_via_earliest_feasible_gets_candidates(desk):
    """H14 failure pin: the reply names W2, so the structured output must
    list it too — the desk ranks in code when the model did not."""
    d = desk.handle_message("ORD-029 is due TODAY. Can we still make it?")
    assert d.behaviour is Behaviour.IMPOSSIBLE
    ids = [c.workshop_id for c in d.candidates]
    assert "W2" in ids and d.chosen.workshop_id == "W2"
    assert any(x["tool"] == "rank_candidates" and x.get("called_by") == "desk"
               for x in d.tool_log)


def test_split_offered_when_faster_than_single(desk):
    d = desk.handle_message("ORD-029 is due TODAY. Can we still make it?")
    assert d.split is not None
    assert d.split["earliest_finish"] < d.split["single_finish"]
    parts = d.split["parts"]
    assert len(parts) == 2 and parts[0]["workshop_id"] != parts[1]["workshop_id"]
    assert sum(p["pieces"] for p in parts) == 1500


def test_split_survives_json_round_trip(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    assert decision_from_dict(to_dict(d)).split == d.split


def test_confirm_split_commits_both_parts(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    before = dict(desk.state.queues)
    records = desk.confirm_split(d, committed_by="dispatcher")
    assert [r.workshop_id for r in records] == [p["workshop_id"] for p in d.split["parts"]]
    assert sum(r.pieces for r in records) == 1500
    assert all(r.order_id == "ORD-029" for r in records)
    assert records[0].evidence["split"] == {"part": 1, "of": 2, "parts": [
        {"workshop_id": p["workshop_id"], "pieces": p["pieces"]} for p in d.split["parts"]]}
    for r in records:      # each part moves only its own workshop's queue
        w = desk.workshops.workshops[r.workshop_id]
        assert desk.state.queues[r.workshop_id] == pytest.approx(
            before[r.workshop_id] + r.pieces / w.capacity * (1 + 0.5 * w.defect_rate))


def test_split_order_cannot_be_committed_again(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    desk.confirm_split(d)
    again = commit_allocation("ORD-029", "W6", desk=desk)
    assert again["committed"] is False and "already committed" in again["error"]
    with pytest.raises(ValueError, match="already committed"):
        desk.confirm_split(desk.refresh(d))
    assert len(desk.audit.load_all()) == 2


def test_stale_split_is_refreshed_not_committed(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    commit_allocation("ORD-041", "W6", desk=desk)      # queues move
    with pytest.raises(ProposalChanged) as exc:
        desk.confirm_split(d)
    assert exc.value.decision.split is not None
    assert desk.audit.load_all()[-1].order_id == "ORD-041"


def test_confirm_split_rejects_tampered_parts(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    bad = dict(d.split, parts=[dict(p) for p in d.split["parts"]])
    bad["parts"][0]["pieces"] += 1                   # no longer adds up
    d.split = bad
    with pytest.raises(ValueError, match="add up"):
        desk.confirm_split(d)
    assert desk.audit.load_all() == []


def test_no_split_for_plain_allocation(desk):
    """An on-time order whose flow never asked about feasibility gets the
    usual single-workshop proposal only."""
    from tests.test_dispatch_safety import FakeAgent
    desk.agent = FakeAgent()
    desk.agent.desk = desk
    d = desk.handle_message("allocate ORD-041")
    assert d.behaviour is Behaviour.ALLOCATE and d.split is None


def test_earliest_feasible_respects_exclusions():
    r = earliest_feasible("ORD-029", excluded=["SteadyHands"])
    assert r["single"]["workshop_id"] != "W2"
    assert all(p["workshop_id"] != "W2" for p in r["split"]["parts"])
    assert "error" in earliest_feasible("ORD-029", excluded=["Nobody"])
