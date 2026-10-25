"""Unit tests for check_eligibility — per-workshop reasons plus the spec's
guard: the tool's eligible set must mirror simulate.eligible_workshops()
for every category/size, so the chat layer and the simulator cannot diverge."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from agent.check_eligibility import WorkshopStore, check_eligibility
from harness.simulate import eligible_workshops


@pytest.fixture(scope="module")
def store():
    return WorkshopStore()


def _eligible_ids(result):
    return {r["workshop_id"] for r in result["workshops"] if r["eligible"]}


def _reasons(result, workshop_id):
    return next(r["reasons"] for r in result["workshops"]
                if r["workshop_id"] == workshop_id)


def test_tops_600_eligible_set(store):
    r = check_eligibility("TOPS", 600, store=store)
    assert _eligible_ids(r) == {"W1", "W2", "W3", "W5", "W6"}
    assert r["eligible_count"] == 5


def test_suspended_workshop_carries_reason(store):
    """OldMill (W7) is suspended — a refusal must be able to say why (R11)."""
    r = check_eligibility("TOPS", 600, store=store)
    assert any("suspended" in s for s in _reasons(r, "W7"))


def test_wrong_category_carries_reason(store):
    """Little Loom (W4) makes accessories only (R24)."""
    r = check_eligibility("TOPS", 300, store=store)
    assert "cannot make TOPS" in _reasons(r, "W4")


def test_failure_over_cap(store):
    """Failure case: 400 pieces exceeds FreshStart's 300-piece trial cap (R08)."""
    r = check_eligibility("TOPS", 400, store=store)
    assert "W8" not in _eligible_ids(r)
    assert any("300-piece cap" in s for s in _reasons(r, "W8"))
    r = check_eligibility("TOPS", 300, store=store)
    assert "W8" in _eligible_ids(r)   # exactly at the cap is allowed


def test_failure_excluded_by_named_person(store):
    """Failure case: 'nothing new to QuickStitch this week' — the Boss's
    constraint (R12) must remove W1 and name who imposed it."""
    r = check_eligibility("TOPS", 800, excluded=["QuickStitch"],
                          excluded_by="Boss", store=store)
    assert "W1" not in _eligible_ids(r)
    assert any("Boss" in s for s in _reasons(r, "W1"))
    # other workshops unaffected
    assert "W5" in _eligible_ids(r)


def test_unknown_exclusion_is_reported_not_silent(store):
    r = check_eligibility("TOPS", 100, excluded=["No Such Shop"], store=store)
    assert r["unresolved_exclusions"] == ["No Such Shop"]


def test_failure_invalid_category(store):
    r = check_eligibility("PANTS", 100, store=store)
    assert "error" in r


def test_failure_bad_pieces(store):
    for bad in (0, -5, "600", None):
        assert "error" in check_eligibility("TOPS", bad, store=store)


def test_mirrors_simulator_rules(store):
    """The guard from the spec: for a spread of batches the tool's eligible
    set (ignoring exclusions) must equal eligible_workshops()."""
    for category in ("TOPS", "ACCESSORIES"):
        for pieces in (1, 300, 301, 600, 2000):
            batch = {"category": category, "pieces": pieces}
            sim_ids = {w.workshop_id
                       for w in eligible_workshops(batch, store.workshops)}
            tool_ids = _eligible_ids(check_eligibility(category, pieces,
                                                       store=store))
            assert tool_ids == sim_ids, (category, pieces)


def test_stages_mode_stage_coverage():
    """--stages: from KNITTING, W6 (WASHING+PACKING only) cannot take the
    batch; without stages it can."""
    base = check_eligibility("ACCESSORIES", 500, store=WorkshopStore())
    assert "W6" in _eligible_ids(base)
    staged = check_eligibility("ACCESSORIES", 500, from_stage="KNITTING",
                               store=WorkshopStore(stages=True))
    assert "W6" not in _eligible_ids(staged)
    assert any("KNITTING" in s for s in _reasons(staged, "W6"))
    assert "W2" in _eligible_ids(staged)   # full-stage shop still fine


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
