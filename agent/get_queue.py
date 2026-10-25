"""
get_queue — how much work each workshop is holding right now.

Spec (roadmap Table 4): input is workshop id(s) (all of them if omitted);
output is days of work held plus the recent change. It does not forecast.

State note: for now the queue comes from workshops.csv `current_queue_days`,
i.e. the 2026-04-01 chat snapshot. When DeskState lands (with
commit_allocation), this tool will read the live chat-side queues from the
desk instead, and `recent_change` will report the delta since the last
commit; the simulator's 1 Jan queues stay separate by design (Assumption 2).
"""

try:
    from .check_eligibility import WorkshopStore
except ImportError:  # run directly as a script: python agent/get_queue.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.check_eligibility import WorkshopStore

CHAT_AS_OF = "2026-04-01"


def get_queue(workshop_ids=None, *, store=None):
    """Queue snapshot for the given workshops (all of them by default).
    Unknown names land in "unknown" instead of failing silently."""
    store = store or WorkshopStore()

    ids, unknown = [], []
    if workshop_ids:
        for name in workshop_ids:
            wid = store.resolve(name)
            (ids.append(wid) if wid else unknown.append(name))
    else:
        ids = list(store.workshops)

    rows = []
    for wid in ids:
        w = store.workshops[wid]
        rows.append({"workshop_id": w.workshop_id, "name": w.name,
                     "queue_days": w.queue0,
                     # no chat-side history yet; DeskState will supply this
                     "recent_change": 0.0})
    result = {"as_of": CHAT_AS_OF, "source": "workshops.csv snapshot (2026-04-01)",
              "workshops": rows}
    if unknown:
        result["unknown"] = unknown
    return result


GET_QUEUE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_queue",
        "description": "Days of work each workshop is currently holding "
                       "(the 2026-04-01 queue snapshot). Call it whenever "
                       "a request mentions speed, capacity or room this week.",
        "parameters": {
            "type": "object",
            "properties": {
                "workshop_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "workshop names or ids "
                                                "(omit for all eight)"},
            },
            "required": [],
        },
    },
}


if __name__ == "__main__":
    import json
    import sys
    arg = sys.argv[1:] or None
    print(json.dumps(get_queue(arg), indent=2))
