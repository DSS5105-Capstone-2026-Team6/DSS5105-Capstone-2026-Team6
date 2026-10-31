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
from desk.tools import (commit_allocation, dispatch_tool, earliest_feasible,
                        split_options)


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


def test_splits_offered_ranked_by_days_late(desk):
    d = desk.handle_message("ORD-029 is due TODAY. Can we still make it?")
    assert d.splits
    lates = [s["days_late"] for s in d.splits]
    assert lates == sorted(lates)
    for s in d.splits:
        ids = [p["workshop_id"] for p in s["parts"]]
        assert len(ids) == len(set(ids)) == s["n_shops"] >= 2
        assert sum(p["pieces"] for p in s["parts"]) == 1500
        assert s["earliest_finish"] < "2026-04-14"          # beats one shop
    # the best option uses three shops: no ceiling on the number of shops
    assert d.splits[0]["n_shops"] == 3 and d.splits[0]["earliest_finish"] == "2026-04-08"


def test_split_survives_json_round_trip(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    assert decision_from_dict(to_dict(d)).splits == d.splits


@pytest.mark.parametrize("index", [0, 1])
def test_confirm_split_commits_every_part(desk, index):
    from dataclasses import replace
    d = desk.handle_message("ORD-029 is due TODAY.")
    # pin lateness: hybrid's plateau keeps only the single best split, but
    # this test exercises committing parts of BOTH ranked options
    d = desk.refresh(replace(d, objective="lateness"))
    chosen = d.splits[index]
    before = dict(desk.state.queues)
    records = desk.confirm_split(d, index, committed_by="dispatcher")
    assert [r.workshop_id for r in records] == [p["workshop_id"] for p in chosen["parts"]]
    assert sum(r.pieces for r in records) == 1500
    assert all(r.order_id == "ORD-029" for r in records)
    assert records[0].evidence["split"] == {"part": 1, "of": len(records), "parts": [
        {"workshop_id": p["workshop_id"], "pieces": p["pieces"]} for p in chosen["parts"]]}
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
    assert len(desk.audit.load_all()) == d.splits[0]["n_shops"]


def test_stale_split_is_refreshed_not_committed(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    commit_allocation("ORD-041", "W6", desk=desk)      # queues move
    with pytest.raises(ProposalChanged) as exc:
        desk.confirm_split(d)
    assert exc.value.decision.splits
    assert desk.audit.load_all()[-1].order_id == "ORD-041"


def test_confirm_split_rejects_tampered_parts(desk):
    d = desk.handle_message("ORD-029 is due TODAY.")
    bad = dict(d.splits[0], parts=[dict(p) for p in d.splits[0]["parts"]])
    bad["parts"][0]["pieces"] += 1                   # no longer adds up
    d.splits = [bad]
    with pytest.raises(ValueError, match="add up"):
        desk.confirm_split(d)
    with pytest.raises(ValueError, match="no such split"):
        desk.confirm_split(d, 5)
    assert desk.audit.load_all() == []


def test_no_split_for_plain_allocation(desk):
    """An on-time order whose flow never asked about feasibility gets the
    usual single-workshop proposal only."""
    from tests.test_dispatch_safety import FakeAgent
    desk.agent = FakeAgent()
    desk.agent.desk = desk
    d = desk.handle_message("allocate ORD-041")
    assert d.behaviour is Behaviour.ALLOCATE and d.splits == []


def test_earliest_feasible_respects_exclusions():
    r = earliest_feasible("ORD-029", excluded=["SteadyHands"])
    assert r["single"]["workshop_id"] != "W2"
    assert all(p["workshop_id"] != "W2" for p in r["split"]["parts"])
    assert "error" in earliest_feasible("ORD-029", excluded=["Nobody"])


def test_two_shop_split_matches_brute_force():
    """The exact search agrees with earliest_feasible's brute force on the
    best two-shop date (it may find a different piece split, same date)."""
    for oid in ("ORD-029", "ORD-103", "ORD-041", "ORD-010"):
        best2 = min((o for o in split_options(oid, top=99)["options"]
                     if o["n_shops"] == 2), key=lambda o: o["earliest_finish"])
        assert best2["earliest_finish"] == earliest_feasible(oid)["split"]["earliest_finish"]


def test_split_parts_respect_caps_and_minimum_share():
    """FreshStart's 300-piece cap holds per part, and no token parts:
    every part carries at least 10% of the order."""
    for o in split_options("ORD-010", top=99)["options"]:
        for p in o["parts"]:
            assert p["pieces"] >= 100
            if p["workshop_id"] == "W8":
                assert p["pieces"] <= 300


def test_extra_shop_must_earn_its_place():
    """A split is dropped when a split over a subset of its shops is at
    least as fast — adding a shop has to make the order earlier."""
    opts = split_options("ORD-010", top=99)["options"]
    for o in opts:
        shops = {p["workshop_id"] for p in o["parts"]}
        assert not any({p["workshop_id"] for p in x["parts"]} < shops
                       and x["est_finish_days"] <= o["est_finish_days"] for x in opts)


def test_impossible_recommends_best_split(desk):
    """On an IMPOSSIBLE order the ⭐ moves to split #1 (it always beats the
    best single shop); `chosen` stays the single-workshop fallback."""
    d = desk.handle_message("ORD-029 is due TODAY.")
    assert d.recommended_split == 0 and d.chosen.workshop_id == "W2"
    assert decision_from_dict(to_dict(d)).recommended_split == 0


def test_allocate_keeps_single_recommendation(desk):
    from tests.test_dispatch_safety import FakeAgent
    desk.agent = FakeAgent()
    desk.agent.desk = desk
    d = desk.handle_message("allocate ORD-041")
    assert d.recommended_split is None


@pytest.mark.parametrize("objective", ["lateness", "defects", "hybrid"])
def test_splits_rank_like_candidates(objective):
    """Split options use the candidates' own ranking (allocator.order_rows)
    under the same objective, not a split-only rule."""
    from desk.allocator import order_rows
    opts = split_options("ORD-029", objective=objective, top=99)["options"]
    assert opts and opts == order_rows(opts, objective)
    if objective == "defects":
        risks = [o["defect_risk"] for o in opts]
        assert risks == sorted(risks)
