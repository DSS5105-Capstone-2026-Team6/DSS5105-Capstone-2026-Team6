"""
probe_overload — what happens to a workshop's queue if it takes more work.

Spec (roadmap Table 4): input is a workshop and additional pieces; output is
the new queue length and the delay imposed on orders already queued. It does
not change state and is read-only by construction: the tool only reads
WorkshopStore, it never writes (a unit test pins queue0 before and after).

The queue model follows the simulator: work beyond daily capacity queues up
first-come-first-served, and the simulator charges a defective batch 1.5x
work (half redone, simulate.py:243-245). So the queue grows by the batch's
EXPECTED work, E[work] = work * (1 + 0.5 * defect_rate) — the same priced
formula harness/algorithm2.py uses everywhere else — and the tool also
reports the defective case so the dispatcher sees the downside. Read-only by
construction: the tool only reads WorkshopStore, it never writes (a unit
test pins queue0 before and after).
"""

try:
    from .check_eligibility import WorkshopStore
except ImportError:  # run directly as a script: python agent/probe_overload.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.check_eligibility import WorkshopStore

# algorithm2.py is a script-style module (imports `simulate` flat), so its
# directory must be importable whether we run as a package or directly.
import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import est_turnaround_expected


def probe_overload(workshop_id=None, additional_pieces=None, *, store=None):
    """Read-only overload probe. Error dicts for unknown workshop or bad
    piece counts — never a silent guess."""
    store = store or WorkshopStore()
    if not workshop_id:
        return {"error": "workshop_id is required"}
    wid = store.resolve(workshop_id)
    if wid is None:
        return {"error": f"unknown workshop {workshop_id!r}"}
    if not isinstance(additional_pieces, int) or additional_pieces <= 0:
        return {"error": f"additional_pieces must be a positive integer, "
                         f"got {additional_pieces!r}"}

    w = store.workshops[wid]
    # expected added work = algorithm2's priced formula, derived from
    # est_turnaround_expected itself (queue 0, transport subtracted) so the
    # single source of truth stays in the harness.
    zero_queues = {i: 0.0 for i in store.workshops}
    batch = {"category": "TOPS", "pieces": additional_pieces,
             "sent_date": None, "due_date": None}
    added = est_turnaround_expected(batch, w, zero_queues) - w.lead_days
    # simulator's defective case: work is redone at 1.5x (simulate.py:245)
    defective_added = additional_pieces / w.capacity * 1.5
    return {"workshop_id": wid, "name": w.name,
            "current_queue_days": w.queue0,
            "added_work_days_expected": round(added, 2),
            "new_queue_days_expected": round(w.queue0 + added, 2),
            # first-come-first-served: the new batch goes to the back, so
            # everything already queued slips by exactly the added work
            "delay_to_queued_orders_days": round(added, 2),
            "defective_case": {
                "added_work_days_if_defective": round(defective_added, 2),
                "new_queue_days_if_defective": round(w.queue0 + defective_added, 2),
                "delay_if_defective": round(defective_added, 2)},
            "read_only": True}


PROBE_OVERLOAD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "probe_overload",
        "description": "What happens to a workshop's queue if it takes more "
                       "pieces: the new queue length and the delay imposed on "
                       "orders already queued. Read-only; call it when a "
                       "request risks overloading a workshop.",
        "parameters": {
            "type": "object",
            "properties": {
                "workshop_id": {"type": "string",
                                "description": "workshop name or id"},
                "additional_pieces": {"type": "integer"},
            },
            "required": ["workshop_id", "additional_pieces"],
        },
    },
}


if __name__ == "__main__":
    import json
    import sys
    workshop = sys.argv[1] if len(sys.argv) > 1 else "Nimble Needle"
    pieces = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    print(f"probe_overload(workshop_id={workshop!r}, additional_pieces={pieces})\n")
    result = probe_overload(workshop, pieces)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if "error" in result:
        raise SystemExit(1)
