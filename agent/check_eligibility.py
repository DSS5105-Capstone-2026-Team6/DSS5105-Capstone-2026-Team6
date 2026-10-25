"""
check_eligibility — for each workshop: eligible yes/no, with the reason.

Spec (roadmap Table 4): input is a category, a batch size and optionally
workshops excluded by a named person; output covers all eight workshops so
refusals can quote the reason. It does not rank or choose. Guard: the
eligible set must mirror simulate.eligible_workshops() — the unit tests
assert the two never diverge.

Rule order for reasons: excluded-by-request, suspended, cannot make the
category, over the per-batch cap, missing stage coverage (--stages mode).
A workshop can fail several rules; all reasons are listed.
"""

try:
    from harness.simulate import load_workshops, eligible_workshops, remaining_stages
except ImportError:  # run directly as a script: python agent/check_eligibility.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from harness.simulate import load_workshops, eligible_workshops, remaining_stages


class WorkshopStore:
    """Loads workshops.csv (or workshops_stages.csv when stages=True) once,
    via the simulator's own loader so the rules can never drift apart."""

    def __init__(self, stages=False):
        self.stages = stages
        self.workshops = load_workshops(stages)
        self._by_name = {w.name.lower(): w.workshop_id for w in self.workshops.values()}

    def resolve(self, name_or_id):
        """'W1' or 'quickstitch' -> 'W1'; None if unknown."""
        if name_or_id in self.workshops:
            return name_or_id
        return self._by_name.get(name_or_id.lower())


def _reasons(w, batch, excluded_by):
    """Every rule w fails, in dispatcher-question order."""
    out = []
    if excluded_by is not None:
        out.append(f"excluded by {excluded_by}")
    if w.status != "ACTIVE":
        out.append("suspended after a quality audit")
    if batch["category"] not in w.makes:
        out.append(f"cannot make {batch['category']}")
    if w.max_batch is not None and batch["pieces"] > w.max_batch:
        out.append(f"batch of {batch['pieces']} exceeds its {w.max_batch}-piece cap")
    missing = remaining_stages(batch) - w.stages
    if missing:
        out.append(f"does not cover stages {sorted(missing)}")
    return out


def check_eligibility(category=None, pieces=None, excluded=None,
                      excluded_by=None, from_stage=None, *, store=None):
    """Eligibility of every workshop for one batch. Returns a dict with a
    per-workshop list; unknown categories / bad sizes return an error dict."""
    store = store or WorkshopStore(stages=from_stage is not None)

    if category not in ("TOPS", "ACCESSORIES"):
        return {"error": f"category must be TOPS or ACCESSORIES, got {category!r}"}
    if not isinstance(pieces, int) or pieces <= 0:
        return {"error": f"pieces must be a positive integer, got {pieces!r}"}

    batch = {"category": category, "pieces": pieces}
    if store.stages:
        batch["from_stage"] = from_stage or "KNITTING"

    excluded_ids, unresolved = set(), []
    for name in excluded or []:
        wid = store.resolve(name)
        (excluded_ids.add(wid) if wid else unresolved.append(name))

    ok_ids = {w.workshop_id for w in eligible_workshops(batch, store.workshops)}

    rows = []
    for w in store.workshops.values():
        reasons = _reasons(w, batch, excluded_by if w.workshop_id in excluded_ids else None)
        # eligible_workshops() is the source of truth for the rule side;
        # exclusion is a per-request constraint layered on top.
        eligible = w.workshop_id in ok_ids and w.workshop_id not in excluded_ids
        if w.workshop_id not in ok_ids and not reasons:
            reasons.append("fails the simulator's eligibility rules")
        rows.append({"workshop_id": w.workshop_id, "name": w.name,
                     "eligible": eligible, "reasons": reasons})

    result = {"category": category, "pieces": pieces,
              "eligible_count": sum(r["eligible"] for r in rows),
              "workshops": rows}
    if unresolved:
        result["unresolved_exclusions"] = unresolved
    return result


CHECK_ELIGIBILITY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_eligibility",
        "description": "For each workshop: can it take this batch yes/no, with "
                       "the reason (suspended, cannot make the category, over "
                       "cap, excluded by a named person, missing stages). Call "
                       "it whenever a message suggests a workshop or asks who "
                       "can take a batch.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["TOPS", "ACCESSORIES"]},
                "pieces": {"type": "integer", "description": "batch size in pieces"},
                "excluded": {"type": "array", "items": {"type": "string"},
                             "description": "workshop names or ids the request excludes"},
                "excluded_by": {"type": "string",
                                "description": "who imposed the exclusion"},
            },
            "required": ["category", "pieces"],
        },
    },
}


if __name__ == "__main__":
    import json
    print(json.dumps(check_eligibility("TOPS", 600), indent=2))
    print(json.dumps(check_eligibility("TOPS", 400, excluded=["FreshStart"],
                                       excluded_by="Priya"), indent=2))
