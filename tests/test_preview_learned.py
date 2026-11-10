"""Scenario preview must use learned capacity once it is active."""

from app.tabs.desk.scenario import compare_sunday
from desk.performance import PerformanceStore
from desk.register import OrderStore, WorkshopStore
from desk.state import DeskState
from datetime import date
from desk import config

def test_preview_eta_moves_with_learned_capacity(tmp_path):
    orders, store = OrderStore(), WorkshopStore()
    queues = dict(DeskState().queues)
    perf = PerformanceStore(tmp_path / "perf.sqlite3")
    before = compare_sunday("ORD-063", orders, store, queues, False, perf=perf)
    wid = before["scenario"][0]["workshop_id"]
    for _ in range(3):   # three very late returns -> learned capacity drops
        perf.observe(wid, 2000, "2026-03-01", "2026-03-20", profile=store.workshops[wid])
    after = compare_sunday("ORD-063", orders, store, queues, False, perf=perf)
    b = {r["workshop_id"]: r["est_finish_days"] for r in before["scenario"]}
    a = {r["workshop_id"]: r["est_finish_days"] for r in after["scenario"]}
    assert a[wid] > b[wid]

def test_preview_uses_order_date_for_both_etas(monkeypatch):
    monkeypatch.setattr(config, "CHAT_AS_OF", "2026-04-01")
    orders, store = OrderStore(), WorkshopStore()
    queues = dict(DeskState().queues)

    result = compare_sunday(
        "ORD-063", orders, store, queues,
        sunday_closed=False,
        transport_delay_days=2,
        preview_date=date(2026, 1, 1),
    )

    assert result["start_date"] == date(2026, 3, 27)

    baseline_w6 = next(
        row for row in result["baseline"] if row["workshop_id"] == "W6"
    )
    scenario_w6 = next(
        row for row in result["scenario"] if row["workshop_id"] == "W6"
    )

    assert baseline_w6["estimated_finish"] == "2026-03-30"
    assert scenario_w6["estimated_finish"] == "2026-04-01"
    assert config.chat_today() == date(2026, 4, 1)