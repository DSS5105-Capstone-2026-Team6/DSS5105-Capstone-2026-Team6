"""
desk — the application core facade: LLM + tools + chat-side state + audit.

The chat agent (desk/agent.py) is the mouth and hands; the desk is the brain
and memory. handle_message() runs one message through the agent and hands
the tool log to desk/router.py, which assembles the structured Decision the
UI renders and the evaluation scores; confirm() is the only path that moves
state, and it goes through commit_allocation.
"""

try:
    from desk.agent import DispatchAgent
    from desk.register import OrderStore
    from desk.tools import commit_allocation
    from desk.router import route
    from .contracts import (Behaviour, Candidate, Decision, ParsedRequest,
                            allocation_from_dict, to_dict)
    from .state import DeskState
    from .audit import AuditLog
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.agent import DispatchAgent
    from desk.register import OrderStore
    from desk.tools import commit_allocation
    from desk.router import route
    from desk.contracts import (Behaviour, Candidate, Decision, ParsedRequest,
                                allocation_from_dict, to_dict)
    from desk.state import DeskState
    from desk.audit import AuditLog


class DispatchDesk:
    def __init__(self, model=None, stages=False, audit_path=None):
        self.agent = DispatchAgent(model=model, stages=stages)
        self.agent.desk = self                  # chat loop passes this to tools
        self.orders = OrderStore(stages=stages)
        self.workshops = self.agent.workshops   # shared with the agent
        self.state = DeskState(stages=stages)
        self.audit = AuditLog(audit_path) if audit_path else AuditLog()

    # ---------------- conversation ----------------

    def handle_message(self, text, requester=None, request_id=None,
                       verbose=False):
        """One chat message -> Decision (candidates + explanation + tool
        log). No state moves here; that only happens in confirm().
        verbose=True streams each tool round to stdout."""
        reply = self.agent.chat(text, verbose=verbose)
        decision = route(text, reply, self.agent.tool_log)
        if request_id is not None:
            decision.request_id = request_id
        return decision

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
    from eval.run_eval import parse_inbox
    req = next(r for r in parse_inbox() if r["request_id"] == "R07")
    desk = DispatchDesk()
    print(f"[R07] {req['speaker']}: {req['text']}\n")
    decision = desk.handle_message(req["text"])
    print(f"behaviour: {decision.behaviour.value}")
    print(f"chosen:    {decision.chosen.workshop_id if decision.chosen else '-'}")
    print(decision.explanation)
