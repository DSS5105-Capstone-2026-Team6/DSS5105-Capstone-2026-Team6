"""
router — code-assigned behaviour: the Decision assembler.

route() reads the tool log of one handled message, never the prose, so the
outcome of the hard cases cannot depend on the LLM's wording. This is the
routing code's v1 (roadmap Table 3): rank_candidates with a winner ->
ALLOCATE; earliest_feasible showing even the split misses -> IMPOSSIBLE;
ambiguous or failed lookup -> ASK; otherwise ANSWER.
"""

try:
    from desk.contracts import Behaviour, Candidate, Decision, ParsedRequest
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.contracts import Behaviour, Candidate, Decision, ParsedRequest

_CANDIDATE_FIELDS = ("workshop_id", "name", "estimated_finish", "days_late",
                     "cost", "defect_risk", "components")


def route(text, reply, log) -> Decision:
    """Assemble the structured Decision from a message, the agent's reply
    and its tool log. No state moves here; that only happens on confirm."""
    def last_ok(name):
        for entry in reversed(log):
            if entry["tool"] == name and "error" not in entry["result"]:
                return entry
        return None

    parsed = ParsedRequest()
    candidates, chosen, behaviour = [], None, Behaviour.ANSWER

    lookup = last_ok("lookup_order")
    if lookup:
        m = lookup["result"]["matches"]
        if lookup["result"]["status"] == "found":
            parsed.order_id = m[0]["order_id"]
            parsed.pieces = int(m[0]["pieces"])
            parsed.category = m[0]["category"]
            parsed.due_date = m[0]["due_date"]
        elif lookup["arguments"].get("order_id"):
            parsed.order_id = lookup["arguments"]["order_id"]

    rank = last_ok("rank_candidates")
    earliest = last_ok("earliest_feasible")

    if rank and rank["result"].get("chosen"):
        behaviour = Behaviour.ALLOCATE
        parsed.order_id = parsed.order_id or rank["arguments"].get("order_id")
        rows = rank["result"]["candidates"]
        candidates = [Candidate(**{k: row[k] for k in _CANDIDATE_FIELDS})
                      for row in rows]
        top = next(r for r in rows if r["workshop_id"] == rank["result"]["chosen"])
        chosen = Candidate(**{k: top[k] for k in _CANDIDATE_FIELDS})
    elif earliest and not (earliest["result"].get("meets_due_split")
                           or earliest["result"].get("meets_due_single")):
        behaviour = Behaviour.IMPOSSIBLE
    elif lookup and lookup["result"]["status"] in ("ambiguous", "not_found"):
        behaviour = Behaviour.ASK

    return Decision(request_id="", behaviour=behaviour, parsed=parsed,
                    candidates=candidates, chosen=chosen,
                    explanation=reply, tool_log=list(log))


if __name__ == "__main__":
    log = [{"tool": "lookup_order", "arguments": {"order_id": "ORD-999"},
            "result": {"status": "not_found", "matches": []}}]
    decision = route("text", "reply", log)
    print(f"behaviour: {decision.behaviour.value}")
    print(f"explanation: {decision.explanation}")
