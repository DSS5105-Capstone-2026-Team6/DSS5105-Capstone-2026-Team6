"""Unit tests for estimate_delivery. The date maths is anchored to the
roadmap's labelled ground truth (Table 7) so a formula change anywhere
(say, in algorithm2) fails here, not at scoring time."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.tools import estimate_delivery
from desk.register import OrderStore, WorkshopStore


@pytest.fixture(scope="module")
def orders():
    return OrderStore()


@pytest.fixture(scope="module")
def store():
    return WorkshopStore()


def test_ground_truth_r04(store):
    """R04: ORD-041 (600 beanies, due Apr 21) at Nimble Needle -> Apr 8.
    Matches the labelled inbox exactly."""
    r = estimate_delivery("ORD-041", "Nimble Needle", store=store)
    assert r["estimated_finish"] == "2026-04-08"
    assert r["days_late"] == 0
    assert r["slack_days"] >= 10
    assert r["cost"] == round(600 * 1.2, 2)
    assert r["defect_risk"] == 0.05
    assert r["estimator"] == "profile_card"


def test_ground_truth_r07(store):
    """R07: ORD-063 (100 cardigans, due Apr 29) at Nimble Needle -> Apr 4."""
    r = estimate_delivery("ORD-063", "W6", store=store)
    assert r["estimated_finish"] == "2026-04-04"
    assert r["days_late"] == 0


def test_components_sum_to_estimate(store):
    """Guard from the spec: the components must add up to the estimate."""
    r = estimate_delivery("ORD-041", "W6", store=store)
    c = r["components"]
    total = c["queue_days"] + c["work_days_expected"] + c["transport_days"]
    assert abs(round(total) - (int(r["estimated_finish"][8:10]) - 1)) <= 1


def test_work_by_id_and_by_name(store):
    a = estimate_delivery("ORD-041", "W6", store=store)
    b = estimate_delivery("ORD-041", "Nimble Needle", store=store)
    assert a == b


def test_late_order_reports_days_late(store):
    """ORD-002 (R28) was due Mar 29 — already overdue on Apr 1."""
    r = estimate_delivery("ORD-002", "QuickStitch", store=store)
    assert r["days_late"] > 0
    assert r["slack_days"] < 0


def test_failure_unknown_order_nearest_match(store):
    """Failure case: ORD-999 must error, never estimate for a similar id."""
    r = estimate_delivery("ORD-999", "W6", store=store)
    assert "error" in r


def test_failure_unknown_workshop(store):
    r = estimate_delivery("ORD-041", "No Such Shop", store=store)
    assert "error" in r


def test_failure_missing_arguments(store):
    assert "error" in estimate_delivery(workshop_id="W6", store=store)
    assert "error" in estimate_delivery(order_id="ORD-041", store=store)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
