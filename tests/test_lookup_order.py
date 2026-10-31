"""Unit tests for lookup_order — happy paths plus one failure case per
behaviour the spec guards (roadmap Table 4: never a nearest match; several
matches must surface as ambiguous, not a guess)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.register import OrderStore
from desk.tools import lookup_order


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
    assert len(r["matches"]) == 12                     # open orders only
    assert r["n_completed_hidden"] == 23
    every = lookup_order(category="ACCESSORIES", include_complete=True, store=store)
    assert len(every["matches"]) == 35


def test_completed_orders_skipped_so_one_is_found_h07(store):
    """H07: 'the Loom & Leaf beanie job' — two of the three beanie orders
    are COMPLETE, so the open one is found instead of a question."""
    r = lookup_order(customer="Loom & Leaf", product="beanie", store=store)
    assert r["status"] == "found" and r["matches"][0]["order_id"] == "ORD-035"
    assert "2 completed" in r["message"]


def test_pieces_filter_resolves_h20(store):
    """H20: 'TrendCart's beanie reorder, 1000 pieces' — two open TrendCart
    beanie orders, only one of 1000 pieces."""
    two = lookup_order(customer="TrendCart", product="beanie", store=store)
    assert two["status"] == "ambiguous"
    assert {m["order_id"] for m in two["matches"]} == {"ORD-096", "ORD-082"}
    one = lookup_order(customer="TrendCart", product="beanie", pieces=1000, store=store)
    assert one["status"] == "found" and one["matches"][0]["order_id"] == "ORD-096"


def test_due_date_filter(store):
    r = lookup_order(customer="TrendCart", product="beanie",
                     due_date="2026-05-01", store=store)
    assert r["status"] == "found" and r["matches"][0]["order_id"] == "ORD-082"


def test_only_completed_matches_is_not_found(store):
    r = lookup_order(customer="Loom & Leaf", product="beanie", pieces=600, store=store)
    assert r["status"] == "not_found" and "ORD-102" in r["message"]


def test_exact_id_still_returns_a_completed_order(store):
    r = lookup_order(order_id="ORD-102", store=store)
    assert r["status"] == "found" and r["matches"][0]["status"] == "COMPLETE"


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


def test_unreadable_due_date_is_ignored_not_a_miss(store):
    r = lookup_order(customer="TrendCart", product="beanie", pieces=1000,
                     due_date="Apr 17", store=store)
    assert r["status"] == "found" and "ignored" in r["message"]
