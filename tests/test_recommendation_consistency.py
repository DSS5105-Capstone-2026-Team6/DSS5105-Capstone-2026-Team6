"""Problem 2 from the held-out review (H09): the text recommended W3 but the
confirm button committed W1. Two fixes: a `cost` objective so "cheapest
that still hits the date" is ranked by the tool, and a router check that
keeps the structured choice in step with the workshop the reply asks the
human to commit to."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.allocator import rank_candidates
from desk.contracts import decision_from_dict, to_dict
from desk.register import WorkshopStore
from desk.router import _reply_workshop, route


@pytest.fixture(scope="module")
def workshops():
    return WorkshopStore()


# ---------------- cost objective ----------------

def test_cost_picks_cheapest_that_meets_due_h09():
    """H09: ORD-010, 1000 cardigans due Apr 25 — BudgetWorks ($800,
    Apr 14) is the cheapest on-time shop; lateness would pick QuickStitch."""
    r = rank_candidates("ORD-010", objective="cost")
    assert r["chosen"] == "W3"
    assert rank_candidates("ORD-010", objective="lateness")["chosen"] == "W1"


def test_cost_never_picks_a_cheaper_late_shop_r21():
    """R21: ORD-081 due Apr 13 — BudgetWorks is cheaper but 3 days late,
    so GiantWeave ($1650, on time) wins."""
    r = rank_candidates("ORD-081", objective="cost")
    assert r["chosen"] == "W5"
    rows = r["candidates"]
    on_time = [c for c in rows if c["days_late"] == 0]
    assert rows[:len(on_time)] == on_time                 # on-time first
    assert [c["cost"] for c in on_time] == sorted(c["cost"] for c in on_time)


def test_cost_falls_back_to_lateness_when_all_late():
    """ORD-029 is due today: nobody is on time, so cost must not pick the
    cheapest late shop — it ranks like lateness."""
    cost = rank_candidates("ORD-029", objective="cost")
    late = rank_candidates("ORD-029", objective="lateness")
    assert [c["workshop_id"] for c in cost["candidates"]] == \
           [c["workshop_id"] for c in late["candidates"]]


# ---------------- reply / choice consistency ----------------

@pytest.mark.parametrize("reply, expected", [
    ("Reply yes to commit ORD-010 to W3 (BudgetWorks) at 800.", "W3"),
    ("Cheapest is BudgetWorks. Reply yes to commit ORD-063 to Nimble Needle.", "W6"),
    ("My recommendation: SteadyHands (W2).", "W2"),
    ("Five workshops can take it; W3 is the cheapest.", None),
])
def test_reply_workshop(workshops, reply, expected):
    assert _reply_workshop(reply, workshops) == expected


def _rank_log(chosen="W1"):
    rows = [{"workshop_id": wid, "name": name, "estimated_finish": "2026-04-10",
             "days_late": 0, "cost": cost, "defect_risk": 0.05, "components": {}}
            for wid, name, cost in (("W1", "QuickStitch", 1500.0),
                                    ("W3", "BudgetWorks", 800.0))]
    rows.sort(key=lambda r: r["workshop_id"] != chosen)
    return [{"tool": "lookup_order", "arguments": {"order_id": "ORD-010"},
             "result": {"status": "found", "matches": [{
                 "order_id": "ORD-010", "pieces": "1000", "category": "TOPS",
                 "due_date": "2026-04-25"}]}},
            {"tool": "rank_candidates", "arguments": {"order_id": "ORD-010"},
             "result": {"chosen": chosen, "candidates": rows}}]


def test_choice_follows_reply_when_valid_candidate(workshops):
    """H09 replay: the ranking chose W1, the text asks to commit W3 — the
    button must commit W3, and the switch is recorded as a warning."""
    d = route("ORD-010 ... cheapest shop that still hits the date",
              "Reply yes to commit ORD-010 to W3 (BudgetWorks) at 800.",
              _rank_log("W1"), workshops=workshops)
    assert d.chosen.workshop_id == "W3"
    assert len(d.warnings) == 1 and "W3" in d.warnings[0] and "W1" in d.warnings[0]
    assert decision_from_dict(to_dict(d)).warnings == d.warnings


def test_mismatch_flagged_when_reply_names_invalid_workshop(workshops):
    d = route("send ORD-010", "Reply yes to commit ORD-010 to OldMill.",
              _rank_log("W1"), workshops=workshops)
    assert d.chosen.workshop_id == "W1"                 # never an invalid pick
    assert len(d.warnings) == 1 and "W7" in d.warnings[0]


def test_no_warning_when_reply_agrees(workshops):
    d = route("send ORD-010", "Reply yes to commit ORD-010 to W1.",
              _rank_log("W1"), workshops=workshops)
    assert d.chosen.workshop_id == "W1" and d.warnings == []


def test_no_check_without_a_choice(workshops):
    """REFUSE / ASK decisions have no chosen workshop: nothing to align."""
    d = route("which order?", "Reply yes to commit ORD-010 to W3.", [],
              workshops=workshops)
    assert d.chosen is None and d.warnings == []
