"""Unit tests for earliest_feasible, anchored to the labelled inbox
(Table 7): R20/R30 give exact dates, R23 shows the split beating the
single batch. The priced work model is shared with the other tools."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs
sys.path.append(str(Path(__file__).parent.parent / "harness"))

import pytest

from desk.tools import earliest_feasible
from desk.register import OrderStore, WorkshopStore


@pytest.fixture(scope="module")
def store():
    return WorkshopStore()


def test_ground_truth_r20_impossible(store):
    """R20: ORD-103 (2000 scarves, due Apr 4) -> earliest Apr 17 single;
    even the split misses, and the tool must say so."""
    r = earliest_feasible("ORD-103", store=store)
    assert r["single"]["earliest_finish"] == "2026-04-17"
    assert r["single"]["workshop_id"] == "W2"
    assert r["meets_due_single"] is False
    assert r["meets_due_split"] is False
    assert r["slack_days_single"] < 0
    # the options the dispatcher needs: a split improves things but stays late
    assert r["split"]["earliest_finish"] < r["single"]["earliest_finish"]


def test_ground_truth_r30_overdue_order(store):
    """R30: ORD-099 (1500 polos, due Apr 5) -> earliest Apr 11 at QuickStitch."""
    r = earliest_feasible("ORD-099", store=store)
    assert r["single"]["earliest_finish"] == "2026-04-11"
    assert r["single"]["workshop_id"] == "W1"
    assert r["meets_due_single"] is False


def test_ground_truth_r23_split_beats_single(store):
    """R23: ORD-005 (500 scarves, due Apr 20) -> single Nimble Needle Apr 7;
    a split (Little Loom + Nimble Needle) is faster."""
    r = earliest_feasible("ORD-005", store=store)
    assert r["single"]["workshop_id"] == "W6"
    assert r["meets_due_single"] and r["meets_due_split"]
    assert r["split"]["earliest_finish"] < r["single"]["earliest_finish"]
    parts = r["split"]["parts"]
    assert sum(p["pieces"] for p in parts) == 500
    assert len({p["workshop_id"] for p in parts}) == 2   # parallel, not serial


def test_split_rescues_over_cap_batch(store):
    """ORD-073 is 400 hoodies: FreshStart (300 cap) is illegal as a single
    batch, but a split can legally put a part there."""
    r = earliest_feasible("ORD-073", store=store)
    assert r["single"]["workshop_id"] != "W8"
    parts = r["split"]["parts"]
    assert sum(p["pieces"] for p in parts) == 400
    # only the part bound for the capped workshop must respect its cap
    for p in parts:
        if p["workshop_id"] == "W8":
            assert p["pieces"] <= 300


def test_split_parts_respect_eligibility(store):
    """Every split part must sit at a workshop that passes the per-part cap
    and category rules — no sneaking oversized parts into FreshStart."""
    r = earliest_feasible("ORD-073", store=store)
    for p in r["split"]["parts"]:
        assert p["workshop_id"] != "W7"          # suspended
        if p["workshop_id"] == "W8":
            assert p["pieces"] <= 300


def test_failure_unknown_order(store):
    r = earliest_feasible("ORD-999", store=store)
    assert "error" in r


def test_advisory_note_present(store):
    r = earliest_feasible("ORD-005", store=store)
    assert "advisory" in r


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
