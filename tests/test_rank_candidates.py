"""Unit tests for rank_candidates. The load-bearing one: the tool's hybrid
winner must equal make_hybrid_allocator (what the simulator actually calls)
on every order — the roadmap requires one allocator, not two that agree."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

from datetime import date

import pytest

from desk.allocator import CHAT_TODAY, rank_candidates
from desk.register import OrderStore, WorkshopStore

_HARNESS = str(Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import make_hybrid_allocator


@pytest.fixture(scope="module")
def orders():
    return OrderStore()


@pytest.fixture(scope="module")
def store():
    return WorkshopStore()


def test_ground_truth_r04(store):
    """R04: ORD-041 (600 beanies, due Apr 21) -> Nimble Needle."""
    r = rank_candidates("ORD-041", objective="hybrid", store=store)
    assert r["chosen"] == "W6"
    assert r["candidates"][0]["name"] == "Nimble Needle"
    assert r["candidates"][0]["estimated_finish"] == "2026-04-08"


def test_matches_simulator_allocator_on_all_orders(orders, store):
    """The guard: tool winner == the allocator the simulator calls, for all
    120 orders, under the chat-side snapshot queues."""
    # tolerance：the day and defect rate trade off
    hybrid = make_hybrid_allocator(0.5)
    queues = {wid: w.queue0 for wid, w in store.workshops.items()}
    mismatches = []
    for rec in orders.orders:
        batch = {"category": rec["category"], "pieces": int(rec["pieces"]),
                 "sent_date": CHAT_TODAY,
                 "due_date": date.fromisoformat(rec["due_date"])}
        sim_winner = hybrid(batch, store.workshops, queues)
        tool = rank_candidates(rec["order_id"], objective="hybrid", store=store)
        if tool["chosen"] != sim_winner:
            mismatches.append((rec["order_id"], tool["chosen"], sim_winner))
    assert not mismatches, mismatches[:5]


def test_lateness_objective_is_sorted(store):
    r = rank_candidates("ORD-040", objective="lateness", store=store)
    late = [c["expected_days_late"] for c in r["candidates"]]
    assert late == sorted(late)
    assert r["chosen"] == r["candidates"][0]["workshop_id"]


def test_defects_objective_is_sorted(store):
    r = rank_candidates("ORD-040", objective="defects", store=store)
    risks = [c["defect_risk"] for c in r["candidates"]]
    assert risks == sorted(risks)


def test_excluded_workshops_are_out(store):
    r = rank_candidates("ORD-041", excluded=["Nimble Needle"], store=store)
    ids = {c["workshop_id"] for c in r["candidates"]}
    assert "W6" not in ids


def test_failure_unknown_order(store):
    r = rank_candidates("ORD-999", store=store)
    assert "error" in r


def test_failure_bad_objective(store):
    r = rank_candidates("ORD-041", objective="cheapest", store=store)
    assert "error" in r


def test_deterministic(store):
    a = rank_candidates("ORD-040", objective="hybrid", store=store)
    b = rank_candidates("ORD-040", objective="hybrid", store=store)
    assert a == b


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
