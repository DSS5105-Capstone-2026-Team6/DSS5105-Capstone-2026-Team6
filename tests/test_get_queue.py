"""Unit tests for get_queue — the 1 April chat snapshot. Failure cases:
unknown workshops must be reported, not dropped silently."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from agent.get_queue import get_queue
from agent.check_eligibility import WorkshopStore


@pytest.fixture(scope="module")
def store():
    return WorkshopStore()


def test_default_returns_all_eight(store):
    r = get_queue(store=store)
    assert len(r["workshops"]) == 8
    assert r["as_of"] == "2026-04-01"


def test_snapshot_values_match_csv(store):
    by_id = {w["workshop_id"]: w["queue_days"] for w in get_queue(store=store)["workshops"]}
    assert by_id["W1"] == 4.0    # QuickStitch, most loaded
    assert by_id["W8"] == 0.0    # FreshStart, empty
    assert by_id["W4"] == 0.5    # Little Loom


def test_subset_by_id(store):
    r = get_queue(["W2", "W6"], store=store)
    assert [w["workshop_id"] for w in r["workshops"]] == ["W2", "W6"]


def test_name_resolution(store):
    r = get_queue(["Nimble Needle"], store=store)
    assert r["workshops"][0]["workshop_id"] == "W6"


def test_failure_unknown_workshop_reported(store):
    """Failure case: 'Quick Stitch' (wrong spelling) must surface, not vanish."""
    r = get_queue(["W1", "Quick Stitch"], store=store)
    assert [w["workshop_id"] for w in r["workshops"]] == ["W1"]
    assert r["unknown"] == ["Quick Stitch"]


def test_no_silent_empty_result(store):
    r = get_queue(["No Such Shop"], store=store)
    assert r["workshops"] == []
    assert r["unknown"] == ["No Such Shop"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
