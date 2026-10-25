"""
desk — the application core: LLM + tools + chat-side state + audit.

The chat agent (agent/llm.py) is the mouth and hands; the desk is the brain
and memory. handle() runs one message through the agent and assembles the
structured Decision the UI renders and the evaluation scores; confirm()
is the only path that moves state, and it goes through commit_allocation.

The behaviour assignment in _decision_from_log is the routing code's v1
(roadmap Table 3): it reads the tool log, never the prose, so the outcome
of the hard cases cannot depend on the LLM's wording.
"""

try:
    from agent.llm import DispatchAgent
    from agent.lookup_order import OrderStore
    from agent.commit_allocation import commit_allocation
    from .contracts import (Behaviour, Candidate, Decision, ParsedRequest,
                            allocation_from_dict, to_dict)
    from .state import DeskState
    from .audit import AuditLog
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.llm import DispatchAgent
    from agent.lookup_order import OrderStore
    from agent.commit_allocation import commit_allocation
    from desk.contracts import (Behaviour, Candidate, Decision, ParsedRequest,
                                allocation_from_dict, to_dict)
    from desk.state import DeskState
    from desk.audit import AuditLog

_CANDIDATE_FIELDS = ("workshop_id", "name", "estimated_finish", "days_late",
                     "cost", "defect_risk", "components")


class DispatchDesk:
    def __init__(self, model=None, stages=False, audit_path=None):
        self.agent = DispatchAgent(model=model, stages=stages)
        self.agent.desk = self                  # chat loop passes this to tools
        self.orders = OrderStore(stages=stages)
        self.workshops = self.agent.workshops   # shared with the agent
        self.state = DeskState(stages=stages)
        self.audit = AuditLog(audit_path) if audit_path else AuditLog()

    # ---------------- conversation ----------------

    def handle(self, text):
        """One chat message -> Decision (candidates + explanation + tool
        log). No state moves here; that only happens in confirm()."""
        reply = self.agent.chat(text)
        return self._decision_from_log(text, reply, self.agent.tool_log)

    def _decision_from_log(self, text, reply, log):
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

    # ---------------- confirmation ----------------

    def confirm(self, decision, committed_by="dispatcher"):
        """The human confirmed: commit the chosen workshop and return the
        audit record. The decision must carry an order and a choice."""
        if decision.chosen is None or not decision.parsed.order_id:
            raise ValueError("nothing to commit: decision has no chosen workshop")
        result = commit_allocation(decision.parsed.order_id,
                                   decision.chosen.workshop_id,
                                   committed_by=committed_by,
                                   orders=self.orders, desk=self)
        if not result["committed"]:
            raise ValueError(result["error"])
        return allocation_from_dict(result["record"])


if __name__ == "__main__":
    from agent.inbox import parse_inbox
    req = next(r for r in parse_inbox() if r["request_id"] == "R07")
    desk = DispatchDesk()
    print(f"[R07] {req['speaker']}: {req['text']}\n")
    decision = desk.handle(req["text"])
    print(f"behaviour: {decision.behaviour.value}")
    print(f"chosen:    {decision.chosen.workshop_id if decision.chosen else '-'}")
    print(decision.explanation)
