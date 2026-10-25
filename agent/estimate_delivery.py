"""
estimate_delivery — finish date, slack, cost and defect risk for one
order at one workshop.

Spec (roadmap Table 4): queue + processing + transport = finish date; slack
against the due date; cost; defect risk. Guard: each component is returned
separately; uses learned performance where available, otherwise the profile
card, and states which.

The time model is harness/algorithm2.py's est_turnaround_expected — the
single source of truth the simulator also uses (defect rework priced at 1.5x,
so E[work] = work * (1 + 0.5 * defect_rate)). The tool only translates its
day-count into dates and adds cost/slack; it never re-derives the formula.

State note: queue days come from the 2026-04-01 chat snapshot for now; when
DeskState lands this tool reads the live chat-side queues instead. The
"estimator" field is the Sprint 3 hook for the adaptive estimator
(update_workshop_performance): "profile_card" today, "learned" later.
"""

from datetime import date, timedelta

try:
    from .lookup_order import OrderStore
    from .check_eligibility import WorkshopStore
except ImportError:  # run directly as a script: python agent/estimate_delivery.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.lookup_order import OrderStore
    from agent.check_eligibility import WorkshopStore

# algorithm2.py is a script-style module (imports `simulate` flat), so its
# directory must be importable whether we run as a package or directly.
import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import est_turnaround_expected

CHAT_TODAY = date(2026, 4, 1)


def estimate_delivery(order_id=None, workshop_id=None, *,
                      orders=None, store=None):
    """Estimate one order at one workshop. Returns an error dict for unknown
    ids — never a nearest match, mirroring lookup_order's guard."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    if not order_id:
        return {"error": "order_id is required"}
    if not workshop_id:
        return {"error": "workshop_id is required"}

    rec = orders.by_id(order_id)
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}
    wid = store.resolve(workshop_id)
    if wid is None:
        return {"error": f"unknown workshop {workshop_id!r}"}
    w = store.workshops[wid]

    pieces = int(rec["pieces"])
    due_date = date.fromisoformat(rec["due_date"])
    batch = {"category": rec["category"], "pieces": pieces,
             "sent_date": CHAT_TODAY, "due_date": due_date}
    queues = {wid2: w2.queue0 for wid2, w2 in store.workshops.items()}

    total_days = est_turnaround_expected(batch, w, queues)
    finish = CHAT_TODAY + timedelta(days=round(total_days))
    work_days = pieces / w.capacity * (1 + 0.5 * w.defect_rate)

    return {"order_id": order_id, "workshop_id": wid, "workshop_name": w.name,
            "estimated_finish": finish.isoformat(),
            "days_late": max(0, (finish - due_date).days),
            "slack_days": (due_date - finish).days,
            "cost": round(pieces * w.cost, 2),
            "defect_risk": w.defect_rate,
            "estimator": "profile_card",
            "as_of": CHAT_TODAY.isoformat(),
            "components": {"queue_days": w.queue0,
                           "work_days_expected": round(work_days, 2),
                           "transport_days": w.lead_days}}


ESTIMATE_DELIVERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "estimate_delivery",
        "description": "Estimated finish date, slack against the due date, "
                       "cost and defect risk for one order at one workshop. "
                       "Call it for every candidate before recommending.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "e.g. ORD-073"},
                "workshop_id": {"type": "string",
                                "description": "workshop name or id"},
            },
            "required": ["order_id", "workshop_id"],
        },
    },
}


if __name__ == "__main__":
    import json
    import sys
    order = sys.argv[1] if len(sys.argv) > 1 else "ORD-041"
    workshop = sys.argv[2] if len(sys.argv) > 2 else "Nimble Needle"
    print(f"estimate_delivery(order_id={order!r}, workshop_id={workshop!r})\n")
    result = estimate_delivery(order, workshop)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if "error" in result:
        raise SystemExit(1)
