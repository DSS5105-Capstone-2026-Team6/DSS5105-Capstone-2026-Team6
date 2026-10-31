"""
rank_candidates — the allocator as an agent-facing tool.

Spec (roadmap Table 4): eligible workshops sorted by the objective score,
with all estimates. It contains no LLM and never commits. The objective is a
configuration parameter ("lateness" | "defects" | "hybrid"), never logic.

The time model comes from harness/algorithm2.py (est_turnaround_expected /
expected_days_late) — the same formulas the simulator runs. The hybrid branch
reimplements the plateau selection of make_hybrid_allocator(late_tol); a unit
test pins the two to the same winner on all 120 orders, so the chat layer
and the simulator cannot diverge. (Refactoring algorithm2 to call this tool
directly is deferred to the wiring pass, to keep the harness diff minimal.)

Constraints honoured today: excluded workshops (by name or id, with the
originator recorded by the caller). More constraint kinds arrive with the
routing code.
"""

from datetime import date, timedelta

try:
    from desk.register import OrderStore, WorkshopStore
except ImportError:  # run directly as a script: python desk/allocator.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.register import OrderStore, WorkshopStore

# algorithm2.py is a script-style module (imports `simulate` flat), so its
# directory must be importable whether we run as a package or directly.
import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import est_turnaround_expected, expected_days_late
from harness.simulate import eligible_workshops

CHAT_TODAY = date(2026, 4, 1)
OBJECTIVES = ("lateness", "defects", "hybrid", "cost")


def _candidate_row(w, batch, queues):
    est = est_turnaround_expected(batch, w, queues)
    finish = CHAT_TODAY + timedelta(days=round(est))
    due = batch["due_date"]
    pieces = batch["pieces"]
    return {"workshop_id": w.workshop_id, "name": w.name,
            "estimated_finish": finish.isoformat(),
            "days_late": max(0, (finish - due).days),
            "cost": round(pieces * w.cost, 2),
            "defect_risk": w.defect_rate,
            "expected_days_late": round(expected_days_late(batch, w, queues), 2),
            "est_finish_days": round(est, 2),
            "components": {"queue_days": queues[w.workshop_id],
                           "work_days_expected": round(
                               pieces / w.capacity * (1 + 0.5 * w.defect_rate), 2),
                           "transport_days": w.lead_days}}


def _sort_key(objective, row):
    if objective == "cost":
        # cheapest among the shops that meet the due date; when none does,
        # fall back to the lateness order (never a cheap-but-late pick)
        on_time = row["days_late"] == 0
        return (not on_time, row["cost"] if on_time else row["expected_days_late"],
                row["est_finish_days"], row["defect_risk"], row["workshop_id"])
    if objective == "defects":
        return (row["defect_risk"], row["expected_days_late"],
                row["est_finish_days"], row["cost"], row["workshop_id"])
    # lateness: expected days late first, then earliest finish
    return (row["expected_days_late"], row["est_finish_days"],
            row["defect_risk"], row["cost"], row["workshop_id"])


def order_rows(rows, objective="lateness", late_tol=0.5):
    """Sort scored rows best-first by the objective. Needs the keys
    expected_days_late, est_finish_days, defect_risk, cost, workshop_id.
    Shared by rank_candidates and the split options, so both rank alike."""
    if objective == "hybrid" and rows:
        # algorithm2.make_hybrid_allocator's plateau, listing everyone in it
        best = min(r["expected_days_late"] for r in rows)
        plateau = [r for r in rows if r["expected_days_late"] <= best + late_tol]
        if best == 0.0:
            earliest = min(r["est_finish_days"] for r in plateau)
            plateau = [r for r in plateau if r["est_finish_days"] <= earliest + late_tol]
        return sorted(plateau,
                      key=lambda r: (r["defect_risk"], r["est_finish_days"],
                                     r["cost"], r["workshop_id"]))
    return sorted(rows, key=lambda r: _sort_key(objective, r))


def rank_candidates(order_id=None, objective="hybrid", late_tol=0.5,
                    excluded=None, *, orders=None, store=None, queues=None):
    """Rank every eligible workshop for an order. Returns candidates sorted
    best-first plus the chosen id; an error dict for a bad order/objective;
    empty candidates when no workshop can take it (never a silent pick).
    `queues` overrides the 1 April snapshot (the desk passes its live
    chat-side queues so earlier commits move later answers)."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    queues = queues or {wid: w.queue0 for wid, w in store.workshops.items()}
    if objective not in OBJECTIVES:
        return {"error": f"objective must be one of {OBJECTIVES}, got {objective!r}"}
    rec = orders.by_id(order_id) if order_id else None
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}

    excluded_ids = set()
    for name in excluded or []:
        wid = store.resolve(name)
        if not wid:
            return {"error": f"unknown excluded workshop {name!r}"}
        excluded_ids.add(wid)

    batch = {"category": rec["category"], "pieces": int(rec["pieces"]),
             "sent_date": CHAT_TODAY,
             "due_date": date.fromisoformat(rec["due_date"])}

    if rec.get("dispatch_stage"):
        batch["from_stage"] = rec["dispatch_stage"]

    ok = [w for w in eligible_workshops(batch, store.workshops)
          if w.workshop_id not in excluded_ids]

    rows = [_candidate_row(w, batch, queues) for w in ok]

    rows = order_rows(rows, objective, late_tol)

    return {"order_id": order_id, "objective": objective, "excluded": sorted(excluded_ids),
            "late_tol": late_tol if objective == "hybrid" else None,
            "chosen": rows[0]["workshop_id"] if rows else None,
            "candidates": rows,
            "n_eligible": len(rows)}


RANK_CANDIDATES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rank_candidates",
        "description": "The allocator: every eligible workshop ranked by the "
                       "objective (lateness first, or defects, or the hybrid "
                       "which keeps the lateness plateau and picks the lowest "
                       "defect rate, or cost: the cheapest shop that still "
                       "meets the due date). THE way to compare or choose workshops: "
                       "call it once per allocation request, instead of "
                       "estimating workshops one by one.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "objective": {"type": "string",
                              "enum": ["lateness", "defects", "hybrid", "cost"],
                              "description": "default hybrid (the production allocator); cost for "
                                             "'cheapest that still hits the date'"},
                "excluded": {"type": "array", "items": {"type": "string"},
                             "description": "workshops the request excludes"},
            },
            "required": ["order_id"],
        },
    },
}


if __name__ == "__main__":
    import json
    import sys
    order = sys.argv[1] if len(sys.argv) > 1 else "ORD-041"
    print(f"rank_candidates(order_id={order!r}, objective='lateness')\n")
    print(json.dumps(rank_candidates(order), indent=2, ensure_ascii=False))
