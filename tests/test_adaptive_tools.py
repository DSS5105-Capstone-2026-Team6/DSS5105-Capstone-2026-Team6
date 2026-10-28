"""Unit tests for the two adaptive tools (roadmap Table 4, §1.6):
update_workshop_performance (learn from returned batches) and flag_at_risk
(early warning on committed batches). Failure cases included: unknown
workshop, bad pieces, malformed dates, learning not active before the
sample threshold, and flag_at_risk refusing to run without a desk."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

import pytest

from desk.performance import MIN_SAMPLES, PerformanceStore
from desk.tools import (dispatch_tool, estimate_delivery, flag_at_risk,
                        update_workshop_performance)


@pytest.fixture()
def perf(tmp_path):
    return PerformanceStore(path=tmp_path / "perf.sqlite3")


def _observe_n(perf, wid, n, delay=3):
    for i in range(n):
        perf.observe(wid, 400, f"2026-03-{10 + i:02d}",
                     f"2026-03-{10 + i + delay:02d}")


# ---------------- update_workshop_performance ----------------

def test_learning_inactive_below_min_samples(perf):
    for i in range(MIN_SAMPLES - 1):
        r = perf.observe("W6", 400, f"2026-03-1{i}", f"2026-03-1{i + 1}")
    assert r["active"] is False
    assert perf.learned("W6") is None      # profile card fallback


def test_learning_activates_at_min_samples(perf):
    _observe_n(perf, "W6", MIN_SAMPLES)
    learned = perf.learned("W6")
    assert learned is not None
    assert learned["observations"] == MIN_SAMPLES
    assert learned["p80_delay"] >= 0


def test_unknown_workshop_and_bad_inputs_fail_loudly(perf):
    assert "error" in update_workshop_performance("NoSuchShop", 400,
                                                  "2026-03-10", "2026-03-12")
    assert "error" in update_workshop_performance("W6", -5,
                                                  "2026-03-10", "2026-03-12")
    assert "error" in update_workshop_performance("W6", 400,
                                                  "tomorrow", "friday")


def test_bounded_update_limits_outlier(perf):
    """One wildly late batch must not swing the capacity ratio more than
    MAX_STEP per observation."""
    _observe_n(perf, "W6", MIN_SAMPLES, delay=1)
    before = perf.learned("W6")["capacity_ratio"]
    perf.observe("W6", 400, "2026-04-01", "2026-06-01")   # 61 days late
    after = perf.learned("W6")["capacity_ratio"]
    assert abs(after - before) <= 0.2 + 1e-9


# ---------------- estimate_delivery learned hook ----------------

def test_estimate_delivery_switches_estimator_when_learned(perf):
    _observe_n(perf, "W6", MIN_SAMPLES, delay=4)
    out = estimate_delivery("ORD-063", "W6", perf=perf)
    assert out["estimator"] == "learned"
    out_default = estimate_delivery("ORD-063", "W1", perf=perf)
    assert out_default["estimator"] == "profile_card"   # W1 never observed


def test_tight_slack_adds_cautious_p80(perf):
    """Learned shop + slack of 0-2 days -> the p80 cautious finish appears."""
    _observe_n(perf, "W6", MIN_SAMPLES, delay=5)
    # find an order that lands 0-2 days of slack at W6 under the learned model
    out = estimate_delivery("ORD-063", "W6", perf=perf)
    if 0 <= out["slack_days"] <= 2:
        assert "cautious" in out
        assert out["cautious"]["p80_delay_days"] >= 5
    else:
        pytest.skip("ORD-063 not tight-slack at W6 under the learned model")


# ---------------- flag_at_risk ----------------

def test_flag_at_risk_requires_desk():
    out = flag_at_risk()
    assert "error" in out and "desk" in out["error"]


def test_flag_at_risk_flags_late_commits(tmp_path):
    """Commit an order whose queue makes it late, then the flag fires with
    the roadmap's four options; a comfortable order stays quiet."""
    from desk.desk import DispatchDesk
    desk = DispatchDesk(audit_path=tmp_path / "audit.jsonl")
    desk.orders.by_id("ORD-063")  # sanity: exists
    # force a huge queue on W1 so the commit projects late
    desk.state.queues["W1"] = 60.0
    rec = desk.audit.allocate(desk.orders.by_id("ORD-063"),
                              desk.workshops.workshops["W1"],
                              committed_by="tester")
    assert rec.order_id == "ORD-063"
    out = flag_at_risk(desk=desk)
    flagged = {r["order_id"] for r in out["at_risk"]}
    assert "ORD-063" in flagged
    assert out["options"] == ["wait", "split the remainder", "reassign",
                              "escalate"]
    assert out["read_only"] is True
    # and the ledger was NOT touched by the read-only flag
    assert len(desk.audit.load_all()) == 1


def test_both_tools_registered_and_dispatchable(tmp_path):
    from desk.desk import DispatchDesk
    desk = DispatchDesk(audit_path=tmp_path / "audit.jsonl")
    out = dispatch_tool("flag_at_risk", {}, desk=desk)
    assert "at_risk" in out
    out = dispatch_tool("update_workshop_performance",
                        {"workshop_id": "W6", "pieces": 400,
                         "promised_date": "2026-03-10",
                         "actual_date": "2026-03-13"}, desk=desk)
    assert "error" not in out
    assert out["observations"] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
