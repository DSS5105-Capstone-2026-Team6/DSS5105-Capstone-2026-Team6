"""
state — the chat-side queue state of the dispatcher desk.

Separate from the simulator by design (roadmap, Assumption 2): the desk
starts from the workshops.csv snapshot (queues on the morning of
2026-04-01) and only commit_allocation moves it, by adding the batch's
expected work. The simulator's 1 Jan queues and queue_free mechanics are
never touched here.

Queue units are days of work; the added work uses the same priced formula
as every other tool (E[work] = work * (1 + 0.5 * defect_rate)), so a commit
makes the desk's own next estimate consistent with what it told the user.
"""

try:
    from desk.register import WorkshopStore
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.register import WorkshopStore

import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.simulate import eligible_workshops

CHAT_AS_OF = "2026-04-01"


class DeskState:
    """Mutable chat-side queues. commit() re-checks eligibility at write
    time (roadmap Table 4 guard) and refuses rather than corrupting state."""

    def __init__(self, stages=False):
        self.workshops = WorkshopStore(stages)
        self.queues = {wid: w.queue0 for wid, w in self.workshops.workshops.items()}

    def commit(self, order_rec, workshop_id):
        """Validate and apply one allocation. Returns (before, after) in
        queue-days, or an error dict when the workshop cannot take it."""
        batch = {"category": order_rec["category"],
                 "pieces": int(order_rec["pieces"])}
        ok = {w.workshop_id for w in eligible_workshops(batch, self.workshops.workshops)}
        if workshop_id not in ok:
            w = self.workshops.workshops.get(workshop_id)
            reason = ("unknown workshop" if w is None else
                      "suspended" if w.status != "ACTIVE" else
                      f"cannot make {batch['category']}" if batch["category"] not in w.makes
                      else f"batch exceeds its {w.max_batch}-piece cap")
            return {"error": f"{workshop_id} cannot take this batch: {reason}. "
                             "Re-check eligibility before committing."}
        w = self.workshops.workshops[workshop_id]
        added = int(order_rec["pieces"]) / w.capacity * (1 + 0.5 * w.defect_rate)
        before = self.queues[workshop_id]
        self.queues[workshop_id] = before + added
        return before, before + added


if __name__ == "__main__":
    s = DeskState()
    print({k: round(v, 2) for k, v in s.queues.items()})
    rec = {"category": "ACCESSORIES", "pieces": 600}
    print("commit 600 ACC -> W6:", s.commit(rec, "W6"))
    print("commit to suspended W7:", s.commit(rec, "W7"))
    print("after:", {k: round(v, 2) for k, v in s.queues.items()})
