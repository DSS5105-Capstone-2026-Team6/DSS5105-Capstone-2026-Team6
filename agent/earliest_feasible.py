"""
earliest_feasible — the earliest achievable date for an order, single batch
or split across two workshops.

Spec (roadmap Table 4): handles the impossible requests (R14, R20, R28, R30)
and split requests (R23); reports when even a split misses the date; splits
are advisory — the simulator sends one batch to one workshop. Eligibility is
re-checked per part, so a split can rescue an over-cap batch (e.g. 400 pieces
past FreshStart's 300 cap becomes two legal parts).

The time model is harness/algorithm2.py's priced formula (defect rework at
its expectation) — the same one estimate_delivery and rank_candidates use.
"""

from datetime import date, timedelta

try:
    from .lookup_order import OrderStore
    from .check_eligibility import WorkshopStore
except ImportError:  # run directly as a script: python agent/earliest_feasible.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.lookup_order import OrderStore
    from agent.check_eligibility import WorkshopStore

# algorithm2.py imports `simulate` flat internally, so harness/ itself must
# be importable too; the harness. prefix keeps the IDE reference resolvable.
import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import est_turnaround_expected
from harness.simulate import eligible_workshops

CHAT_TODAY = date(2026, 4, 1)


def _eligible_for(pieces, category, store):
    """Eligible workshops for a part of this size — the simulator's own
    rule, so per-part eligibility can never drift from the rest."""
    batch = {"category": category, "pieces": pieces}
    return eligible_workshops(batch, store.workshops)


def _finish(pieces, w, queues):
    batch = {"pieces": pieces}
    return est_turnaround_expected(batch, w, queues)


def earliest_feasible(order_id=None, *, orders=None, store=None):
    """Earliest date as one batch and as a two-way split. Error dict for an
    unknown order; flags report when even the split misses the due date."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    rec = orders.by_id(order_id) if order_id else None
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}

    pieces, category = int(rec["pieces"]), rec["category"]
    due = date.fromisoformat(rec["due_date"])
    queues = {wid: w.queue0 for wid, w in store.workshops.items()}

    # --- single batch: earliest finish over all eligible workshops
    single = None   # (finish date, workshop)
    for w in _eligible_for(pieces, category, store):
        finish = CHAT_TODAY + timedelta(days=round(_finish(pieces, w, queues)))
        if single is None or finish < single[0]:
            single = (finish, w)

    # --- split across two different workshops, every size combination
    best_split = None
    elig_cache = {}

    def elig(n):
        if n not in elig_cache:
            elig_cache[n] = _eligible_for(n, category, store)
        return elig_cache[n]

    for a in range(1, pieces):
        b = pieces - a
        for w1 in elig_cache.setdefault(a, _eligible_for(a, category, store)):
            f1 = _finish(a, w1, queues)
            for w2 in elig_cache.setdefault(b, _eligible_for(b, category, store)):
                if w2.workshop_id == w1.workshop_id:
                    continue            # same shop = serial, no parallelism
                f2 = _finish(b, w2, queues)
                finish = CHAT_TODAY + timedelta(days=round(max(f1, f2)))
                if best_split is None or finish < best_split[0]:
                    best_split = (finish, w1, a, w2, b)

    def _slack(finish_iso):
        return (due - date.fromisoformat(finish_iso)).days if finish_iso else None

    single_out = ({"earliest_finish": single[0].isoformat(),
                   "workshop_id": single[1].workshop_id, "name": single[1].name}
                  if single else None)
    split_out = ({"earliest_finish": best_split[0].isoformat(),
                  "parts": [{"workshop_id": best_split[1].workshop_id,
                             "name": best_split[1].name, "pieces": best_split[2]},
                            {"workshop_id": best_split[3].workshop_id,
                             "name": best_split[3].name, "pieces": best_split[4]}]}
                 if best_split else None)

    return {"order_id": order_id, "due_date": due.isoformat(),
            "single": single_out, "split": split_out,
            "meets_due_single": bool(single_out and single_out["earliest_finish"] <= due.isoformat()),
            "meets_due_split": bool(split_out and split_out["earliest_finish"] <= due.isoformat()),
            "slack_days_single": _slack(single_out and single_out["earliest_finish"]),
            "slack_days_split": _slack(split_out and split_out["earliest_finish"]),
            "advisory": "splits are advisory; the simulator sends one batch "
                        "to one workshop (roadmap, Assumption 4)"}


EARLIEST_FEASIBLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "earliest_feasible",
        "description": "Earliest achievable delivery date for an order — as "
                       "one batch and split across two shops. Use it for "
                       "impossible-looking dates and when a request asks "
                       "about splitting.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
}


if __name__ == "__main__":
    import json
    import sys
    order = sys.argv[1] if len(sys.argv) > 1 else "ORD-103"
    print(f"earliest_feasible(order_id={order!r})\n")
    result = earliest_feasible(order)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if "error" in result:
        raise SystemExit(1)
