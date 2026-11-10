"""Scenario preview must use learned capacity once it is active."""

from app.tabs.desk.scenario import compare_sunday
from desk.performance import PerformanceStore
from desk.register import OrderStore, WorkshopStore
from desk.state import DeskState


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
