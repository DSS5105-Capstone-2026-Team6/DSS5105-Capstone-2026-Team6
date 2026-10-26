"""Unit tests for probe_overload — the spec's guard is read-only by
construction: state must be untouched by the call."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.tools import probe_overload
from desk.register import WorkshopStore


@pytest.fixture(scope="module")
def store():
    return WorkshopStore()


def test_nimble_needle_500(store):
    """Nimble Needle (cap 130/day, queue 1.0, defect 5%) + 500 pcs:
    expected added work prices the defect rework in (algorithm2's formula)."""
    r = probe_overload("W6", 500, store=store)
    expected = round(500 / 130 * (1 + 0.5 * 0.05), 2)
    assert r["added_work_days_expected"] == expected
    assert r["new_queue_days_expected"] == round(1.0 + expected, 2)
    assert r["delay_to_queued_orders_days"] == r["added_work_days_expected"]
    assert r["defective_case"]["added_work_days_if_defective"] == round(500 / 130 * 1.5, 2)
    assert r["read_only"] is True


def test_defect_pricing_beats_plain_work(store):
    """The priced formula must exceed the plain pieces/capacity — otherwise
    the tool has drifted back to the unpriced model."""
    r = probe_overload("W1", 1000, store=store)   # QuickStitch, defect 12%
    assert r["added_work_days_expected"] > 1000 / 300


def test_empty_workshop(store):
    """FreshStart starts empty: the delay equals its own added work."""
    r = probe_overload("FreshStart", 300, store=store)
    assert r["current_queue_days"] == 0.0
    assert r["new_queue_days_expected"] == round(300 / 100 * (1 + 0.5 * 0.04), 2)


def test_failure_unknown_workshop(store):
    r = probe_overload("No Such Shop", 100, store=store)
    assert "error" in r


def test_failure_bad_pieces(store):
    for bad in (0, -100, "500", None):
        assert "error" in probe_overload("W6", bad, store=store)


def test_read_only_guard(store):
    """Failure case per the spec: the probe must never mutate state."""
    before = {wid: w.queue0 for wid, w in store.workshops.items()}
    probe_overload("W6", 5000, store=store)
    probe_overload("W6", 1, store=store)
    after = {wid: w.queue0 for wid, w in store.workshops.items()}
    assert before == after


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
