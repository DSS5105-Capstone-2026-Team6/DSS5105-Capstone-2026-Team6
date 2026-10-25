"""
commit_allocation — write the audited allocation, after human confirmation.

Spec (roadmap Table 4): produces the structured record the group chat
lacks; runs only after human confirmation; re-checks eligibility before
writing; the log is append-only. State and persistence live in the desk
(desk.state / desk.audit) — this tool is deliberately thin: validate,
apply, record, report. Without a desk there is nothing to commit to.
"""

from datetime import datetime

try:
    from desk.contracts import AllocationRecord, to_dict
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.contracts import AllocationRecord, to_dict


def commit_allocation(order_id=None, workshop_id=None,
                      committed_by="dispatcher", *, orders=None, desk=None):
    """Confirm an allocation: re-check eligibility, move the chat-side
    queue, append the audit record. Returns {"committed": True, "record"}
    or {"committed": False, "error"} — never a silent write."""
    if desk is None:
        return {"committed": False,
                "error": "commit_allocation needs a desk context (state + audit)"}
    orders = orders or desk.orders
    if not order_id or not workshop_id:
        return {"committed": False,
                "error": "order_id and workshop_id are required"}
    rec = orders.by_id(order_id)
    if rec is None:
        return {"committed": False, "error": f"unknown order {order_id!r}"}
    wid = desk.workshops.resolve(workshop_id)
    if wid is None:
        return {"committed": False, "error": f"unknown workshop {workshop_id!r}"}

    result = desk.state.commit(rec, wid)
    if isinstance(result, dict):                    # eligibility re-check failed
        return {"committed": False, **result}
    queue_before, queue_after = result

    record = AllocationRecord(
        record_id=f"A-{len(desk.audit.load_all()) + 1:04d}",
        decision_id=order_id, order_id=order_id, workshop_id=wid,
        pieces=int(rec["pieces"]), committed_by=committed_by,
        committed_at=datetime.now().isoformat(timespec="seconds"),
        queue_before=round(queue_before, 2), queue_after=round(queue_after, 2))
    desk.audit.append(record)
    return {"committed": True, "record": to_dict(record)}


COMMIT_ALLOCATION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "commit_allocation",
        "description": "Commit an allocation after the human dispatcher "
                       "confirms: re-checks eligibility, updates the queue "
                       "and writes the append-only audit record. Never call "
                       "it without an explicit confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "workshop_id": {"type": "string"},
                "committed_by": {"type": "string",
                                 "description": "who confirmed"},
            },
            "required": ["order_id", "workshop_id"],
        },
    },
}


if __name__ == "__main__":
    from desk.desk import DispatchDesk
    import json
    desk = DispatchDesk()
    print(json.dumps(commit_allocation("ORD-041", "Nimble Needle",
                                       desk=desk), indent=2))
    print("queues now:", {k: round(v, 2) for k, v in desk.state.queues.items()})
