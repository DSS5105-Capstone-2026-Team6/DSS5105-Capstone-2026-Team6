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

import re

_YES_WORDS = ("yes", "y", "yep", "yes please", "ok", "okay", "sure",
              "commit", "confirm", "confirmed", "go ahead", "please do",
              "do it", "sounds good", "确认", "好的", "行", "可以")

_OPTIONS_LINE = re.compile(r"(?im)^OPTIONS:\s*(.+?)\s*$")


def looks_like_confirmation(text):
    """Deterministic yes-detector for follow-up messages: when the agent has
    just asked 'Reply yes to commit ...', a bare affirmation commits without
    another LLM round-trip. Deliberately conservative — anything with a
    'but' or a question mark is a conversation, not a confirmation."""
    t = (text or "").strip().lower().rstrip(".!。")
    return t in _YES_WORDS or t.startswith(("yes,", "yes do", "yes commit"))


def commit_intent_workshop(text, decision):
    """A follow-up that names a workshop together with an action word commits
    THAT candidate ('commit to W2', 'send it to SteadyHands') — any candidate,
    not just the buttoned top three. A bare affirmation commits the
    recommended one. Returns a workshop_id, or None when the message is
    conversation rather than an instruction."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if looks_like_confirmation(t):
        return decision.chosen.workshop_id if decision.chosen else None
    action_words = ("commit", "confirm", "book", "send", "use", "go with",
                    "place", "assign", "give", "确认", "定给", "就用", "派给")
    if not any(w in t for w in action_words):
        return None
    for c in decision.candidates or []:
        if c.workshop_id.lower() in t or c.name.lower() in t:
            return c.workshop_id
    return None


def extract_options(explanation):
    """Split the machine-readable OPTIONS line off the reply. Returns
    (clean_explanation, options): 'OPTIONS: ORD-061 | ORD-108' becomes
    buttons in the UI; tapping one sends that text back as the follow-up."""
    m = _OPTIONS_LINE.search(explanation or "")
    if not m:
        return (explanation or "").strip(), []
    options = [o.strip() for o in m.group(1).split("|") if o.strip()]
    clean = _OPTIONS_LINE.sub("", explanation).strip()
    return clean, options


class DispatchDesk:
    def __init__(self, model=None, stages=False, audit_path=None,
                 provider=None, api_key=None, persona="dispatcher"):
        from desk.config import DEFAULT_PROVIDER
        self.agent = DispatchAgent(model=model, stages=stages, api_key=api_key,
                                   provider=provider or DEFAULT_PROVIDER,
                                   persona=persona)
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
        decision = route(text, reply, self.agent.tool_log,
                         workshops=self.workshops)
        if request_id is not None:
            decision.request_id = request_id
        # an OPTIONS line in the reply becomes tappable choices (unless the
        # router already attached some, e.g. ambiguous lookup matches)
        if not decision.options:
            decision.explanation, decision.options = extract_options(
                decision.explanation)
        # the model may skip lookup_order and call rank_candidates directly;
        # fill any missing parsed fields from the register so the UI card and
        # slack math never show blanks
        p = decision.parsed
        if p.order_id and p.pieces is None:
            rec = self.orders.by_id(p.order_id)
            if rec is not None:
                p.pieces = int(rec["pieces"])
                p.category = rec["category"]
                p.due_date = rec["due_date"]
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
