"""
router — code-assigned behaviour: the Decision assembler (v2).

route() reads the tool log of one handled message, never the prose, so the
outcome of the hard cases cannot depend on the LLM's wording. v2 priority:

    REFUSE      the message names a workshop the tools ruled ineligible
                (reasons that are only "excluded by ..." don't count — that
                is a constraint, not a refusal)
    ALLOCATE    a successful rank_candidates whose order is the one the
                message asked about (a rank for a *different* order — e.g.
                the model guessed one after a not_found lookup — is ignored)
    IMPOSSIBLE  earliest_feasible shows even the split misses the due date
    ASK         lookup_order returned several matches (ask, don't guess)
    NO_DATA     lookup_order found nothing for the id/filters the message gave
    ANSWER      everything else (register questions, missing-info asks)
"""

import re

try:
    from desk.contracts import Behaviour, Candidate, Decision, ParsedRequest
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.contracts import Behaviour, Candidate, Decision, ParsedRequest

_CANDIDATE_FIELDS = ("workshop_id", "name", "estimated_finish", "days_late",
                     "cost", "defect_risk", "components")


def _suggested_workshop_id(text, workshops):
    """First workshop name that appears in the message (word-boundary,
    case-insensitive), resolved to an id; None when no name matches."""
    if workshops is None or not text:
        return None
    lowered = text.lower()
    for w in workshops.workshops.values():
        if re.search(r"\b" + re.escape(w.name.lower()) + r"\b", lowered):
            return w.workshop_id
    return None


def _eligibility_row(elig_call, workshop_id):
    for row in elig_call["result"].get("workshops", []):
        if row["workshop_id"] == workshop_id:
            return row
    return None


def route(text, reply, log, workshops=None) -> Decision:
    """Assemble the structured Decision from a message, the agent's reply and
    its tool log. No state moves here; that only happens on confirm."""

    def last_ok(name):
        for entry in reversed(log):
            if entry["tool"] == name and "error" not in entry["result"]:
                return entry
        return None

    parsed = ParsedRequest()
    candidates, chosen, behaviour = [], None, Behaviour.ANSWER

    lookup = last_ok("lookup_order")
    requested_id = lookup["arguments"].get("order_id") if lookup else None
    if lookup:
        m = lookup["result"]["matches"]
        if lookup["result"]["status"] == "found":
            parsed.order_id = m[0]["order_id"]
            parsed.pieces = int(m[0]["pieces"])
            parsed.category = m[0]["category"]
            parsed.due_date = m[0]["due_date"]
        elif requested_id:
            parsed.order_id = requested_id

    rank = last_ok("rank_candidates")
    earliest = last_ok("earliest_feasible")
    elig = last_ok("check_eligibility")

    # a rank only counts when it is about the order the message asked about
    rank_relevant = bool(rank and rank["result"].get("chosen") and (
        not requested_id
        or rank["arguments"].get("order_id") == requested_id))

    # 1. REFUSE: message names a workshop the tools ruled ineligible
    suggested_id = _suggested_workshop_id(text, workshops)
    if suggested_id and elig:
        row = _eligibility_row(elig, suggested_id)
        if row and not row["eligible"]:
            hard_reasons = [r for r in row["reasons"]
                            if not r.startswith("excluded by")]
            if hard_reasons:
                behaviour = Behaviour.REFUSE
                parsed.suggested_workshop = row["name"]

    # 2. ALLOCATE from a consistent rank (candidates also attach to REFUSE
    #    as the alternatives the reply offers)
    if rank_relevant:
        parsed.order_id = parsed.order_id or rank["arguments"].get("order_id")
        rows = rank["result"]["candidates"]
        candidates = [Candidate(**{k: row[k] for k in _CANDIDATE_FIELDS})
                      for row in rows]
        if behaviour is not Behaviour.REFUSE:
            behaviour = Behaviour.ALLOCATE
            top = next(r for r in rows
                       if r["workshop_id"] == rank["result"]["chosen"])
            chosen = Candidate(**{k: top[k] for k in _CANDIDATE_FIELDS})

    if behaviour is Behaviour.ANSWER:
        # 3. IMPOSSIBLE: even the split misses the due date
        if earliest and not (earliest["result"].get("meets_due_split")
                             or earliest["result"].get("meets_due_single")):
            behaviour = Behaviour.IMPOSSIBLE
        # 4. ASK: several matches — ask which one, never guess
        elif lookup and lookup["result"]["status"] == "ambiguous":
            behaviour = Behaviour.ASK
        # 5. NO_DATA: the message referenced something the data doesn't hold
        elif lookup and lookup["result"]["status"] == "not_found" and (
                requested_id or lookup["arguments"].get("customer")
                or lookup["arguments"].get("product")
                or lookup["arguments"].get("category")):
            behaviour = Behaviour.NO_DATA

    return Decision(request_id="", behaviour=behaviour, parsed=parsed,
                    candidates=candidates, chosen=chosen,
                    explanation=reply, tool_log=list(log))


if __name__ == "__main__":
    log = [{"tool": "lookup_order", "arguments": {"order_id": "ORD-999"},
            "result": {"status": "not_found", "matches": []}}]
    decision = route("text", "reply", log)
    print(f"behaviour: {decision.behaviour.value}")
    print(f"explanation: {decision.explanation}")
