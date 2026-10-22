"""Unit tests for lookup_order — happy paths plus one failure case per
behaviour the spec guards (roadmap Table 4: never a nearest match; several
matches must surface as ambiguous, not a guess)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from agent.lookup_order import OrderStore, lookup_order


@pytest.fixture(scope="module")
def store():
    return OrderStore()


@pytest.fixture(scope="module")
def stages_store():
    return OrderStore(stages=True)


def test_exact_id_found(store):
    r = lookup_order(order_id="ORD-063", store=store)
    assert r["status"] == "found"
    assert len(r["matches"]) == 1
    m = r["matches"][0]
    assert m["order_id"] == "ORD-063"
    assert m["customer"] == "Loom & Leaf"
    assert m["category"] == "TOPS"
    assert m["pieces"] == "100"
    assert m["due_date"] == "2026-04-29"
    assert m["current_stage"] == "KNITTING"


def test_unknown_id_not_found_never_nearest(store):
    """Failure case: ORD-999 does not exist (R18). Must not return ORD-099
    or any other order."""
    r = lookup_order(order_id="ORD-999", store=store)
    assert r["status"] == "not_found"
    assert r["matches"] == []


def test_ambiguous_customer_returns_all_matches(store):
    """Failure case: 'TrendCart' has 6 open orders (R03) — ask, don't guess."""
    r = lookup_order(customer="TrendCart", store=store)
    assert r["status"] == "ambiguous"
    assert len(r["matches"]) > 1
    assert all(m["customer"] == "TrendCart" for m in r["matches"])
    in_progress = [m for m in r["matches"] if m["status"] == "IN_PROGRESS"]
    assert len(in_progress) == 6


def test_customer_filter_is_case_insensitive(store):
    r = lookup_order(customer="trendcart", store=store)
    assert r["status"] == "ambiguous"


def test_category_filter(store):
    r = lookup_order(category="ACCESSORIES", store=store)
    assert r["status"] == "ambiguous"
    assert all(m["category"] == "ACCESSORIES" for m in r["matches"])
    assert len(r["matches"]) == 35


def test_combined_filters_single_hit(store):
    r = lookup_order(customer="Loom & Leaf", product="Cardigan",
                     category="TOPS", store=store)
    assert r["status"] in {"found", "ambiguous"}
    assert all(m["customer"] == "Loom & Leaf" and m["category"] == "TOPS"
               for m in r["matches"])


def test_filters_with_no_match(store):
    """Failure case: a filter combination nothing satisfies."""
    r = lookup_order(customer="No Such Customer", store=store)
    assert r["status"] == "not_found"
    assert r["matches"] == []


def test_no_arguments_is_a_safe_failure(store):
    """Failure case: an empty call must not dump all 120 orders."""
    r = lookup_order(store=store)
    assert r["status"] == "not_found"
    assert r["matches"] == []


def test_stages_mode_exposes_dispatch_stage(stages_store):
    r = lookup_order(order_id="ORD-063", store=stages_store)
    assert r["status"] == "found"
    assert r["matches"][0]["dispatch_stage"] == "KNITTING"


def test_default_mode_has_no_dispatch_stage(store):
    r = lookup_order(order_id="ORD-063", store=store)
    assert "dispatch_stage" not in r["matches"][0]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
