"""
desk — the application core facade: LLM + tools + chat-side state + audit.

The chat agent (desk/agent.py) is the mouth and hands; the desk is the brain
and memory. handle_message() runs one message through the agent and hands
the tool log to desk/router.py, which assembles the structured Decision the
UI renders and the evaluation scores; confirm() is the only path that moves
state through the transactional allocation ledger.
"""

try:
    from desk.agent import DispatchAgent
    from desk.register import OrderStore
    from desk.router import candidates_from_rank, route
    from .contracts import to_dict
    from .state import DeskState
    from .audit import AuditLog
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.agent import DispatchAgent
    from desk.register import OrderStore
    from desk.router import candidates_from_rank, route
    from desk.contracts import to_dict
    from desk.state import DeskState
    from desk.audit import AuditLog

import re

from dataclasses import replace
from datetime import datetime, timezone
from desk.confirmation import (commit_intent_workshop, fast_intent,
                           looks_like_confirmation)
from desk.audit import StaleAllocation
from desk.allocator import rank_candidates
from desk.contracts import Behaviour, Constraint, canonical_order_id
from desk.tools import earliest_feasible

_OPTIONS_LINE = re.compile(r"(?im)^OPTIONS:\s*(.+?)\s*$")


class ProposalChanged(ValueError):
    def __init__(self, decision):
        super().__init__("Queues changed. Review the updated proposal and confirm again.")
        self.decision = decision



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


def _restore_user_text(agent, wrapped, text):
    """The conversation history (which the UI renders) records the user's
    own words, not the internal context a follow-up wraps around them."""
    history = getattr(agent, "history", None)
    if not isinstance(history, list):
        return
    for i in range(len(history) - 1, -1, -1):
        m = history[i]
        if isinstance(m, dict) and m.get("role") == "user" and m.get("content") == wrapped:
            history[i] = {**m, "content": text}
            return


class DispatchDesk:
    def __init__(self, model=None, stages=False, audit_path=None,
                 provider=None, api_key=None, persona="dispatcher", agent=None):
        from desk.config import DEFAULT_PROVIDER
        self.agent = agent or DispatchAgent(model=model, stages=stages, api_key=api_key,
                                   provider=provider or DEFAULT_PROVIDER,
                                   persona=persona)
        self.agent.desk = self                  # chat loop passes this to tools
        self.orders = OrderStore(stages=stages)
        self.workshops = self.agent.workshops   # shared with the agent
        self.state = DeskState(stages=stages)
        audit_kwargs = {"initial_queues": self.state.queues}
        self.audit = AuditLog(audit_path, **audit_kwargs) if audit_path else AuditLog(**audit_kwargs)
        self.state.audit = self.audit
        from desk.performance import PerformanceStore
        self.performance = PerformanceStore()   # learned shop performance,
                                                # shared via the ledger db

    # ---------------- conversation ----------------

    def handle_message(self, text, requester=None, request_id=None,
                       verbose=False):
        """One chat message -> Decision (candidates + explanation + tool
        log). No state moves here; that only happens in confirm().
        verbose=True streams each tool round to stdout."""
        version = self.audit.version
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
        decision.state_version = version
        decision.created_at = datetime.now(timezone.utc).isoformat()
        self._attach_ranking(decision, requester or "dispatcher")
        self._fill_impossible(decision)
        self._attach_split(decision)
        return decision

    def _fill_impossible(self, decision):
        """An IMPOSSIBLE reached through earliest_feasible alone has no
        candidates, yet the reply names workshops. Rank in code so the
        structured output lists every shop and the best late option."""
        if (decision.behaviour is not Behaviour.IMPOSSIBLE or decision.candidates
                or self.orders.by_id(decision.parsed.order_id) is None):
            return
        args = {"order_id": decision.parsed.order_id, "objective": decision.objective,
                "excluded": list(decision.excluded)}
        result = rank_candidates(**args, orders=self.orders, store=self.workshops,
                                 queues=self.state.queues)
        if "error" in result:
            return
        decision.tool_log.append({"tool": "rank_candidates", "arguments": args,
                                  "result": result, "called_by": "desk"})
        decision.candidates, decision.chosen = candidates_from_rank(result)

    def _attach_split(self, decision, force=False):
        """Offer a two-workshop split when it finishes earlier than the best
        single batch: always for IMPOSSIBLE, and for an ALLOCATE whose flow
        asked earliest_feasible (e.g. the message asked about splitting) or
        that is a refresh of a proposal which already offered one.
        Splits live in the chat layer; the simulator stays single-batch."""
        oid = decision.parsed.order_id
        asked = force or any(x["tool"] == "earliest_feasible" for x in decision.tool_log)
        if (self.orders.by_id(oid) is None
                or decision.behaviour not in (Behaviour.IMPOSSIBLE, Behaviour.ALLOCATE)
                or (decision.behaviour is Behaviour.ALLOCATE and not asked)):
            decision.split = None
            return
        args = {"order_id": oid, "excluded": list(decision.excluded)}
        result = earliest_feasible(**args, orders=self.orders, store=self.workshops,
                                   queues=self.state.queues)
        split, single = result.get("split"), result.get("single")
        if "error" in result or not split or (
                single and split["earliest_finish"] >= single["earliest_finish"]):
            decision.split = None
            return
        decision.tool_log.append({"tool": "earliest_feasible", "arguments": args,
                                  "result": result, "called_by": "desk"})
        decision.split = {"earliest_finish": split["earliest_finish"],
                          "meets_due": result["meets_due_split"],
                          "single_finish": single and single["earliest_finish"],
                          "parts": [dict(part) for part in split["parts"]]}

    def _attach_ranking(self, decision, requester):
        ranks = [x for x in decision.tool_log if x["tool"] == "rank_candidates"
                 and "error" not in x["result"]
                 and x["arguments"].get("order_id") == decision.parsed.order_id]
        if ranks:
            args = ranks[-1]["arguments"]
            decision.objective = args.get("objective", "lateness")
            decision.excluded = list(ranks[-1]["result"].get("excluded", args.get("excluded")) or [])
            decision.parsed.constraints = [Constraint("exclude", requester, x)
                                           for x in decision.excluded]

    def refresh(self, decision):
        version = self.audit.version
        result = rank_candidates(decision.parsed.order_id, decision.objective,
                                 excluded=decision.excluded, orders=self.orders,
                                 store=self.workshops, queues=self.state.queues)
        fresh = route("", "Queues changed. Please review these updated candidates and confirm again.",
                      [{"tool": "rank_candidates",
                        "arguments": {"order_id": decision.parsed.order_id,
                                      "objective": decision.objective,
                                      "excluded": decision.excluded}, "result": result}],
                      workshops=self.workshops)
        fresh.parsed = replace(decision.parsed)
        fresh.objective, fresh.excluded = decision.objective, list(decision.excluded)
        fresh.state_version = version
        fresh.created_at = datetime.now(timezone.utc).isoformat()
        self._attach_split(fresh, force=decision.split is not None)
        return fresh

    def follow_up(self, text, decision, requester="dispatcher"):
        """Return (updated decision or None, committed record or None, reply).

        A missing decision invalidates all old confirm buttons. Both adapters
        use this entry point; the language model never owns a write capability.
        """
        if not decision.candidates and (not decision.parsed.order_id
                                        or self.orders.by_id(decision.parsed.order_id) is None):
            # Nothing real to preserve (e.g. the order was not found): treat the
            # follow-up as a fresh message instead of a proposal for a
            # non-existent order.
            fresh = self.handle_message(text, requester=requester)
            return fresh, None, fresh.explanation
        intent = fast_intent(text, decision)
        if intent is None:
            intent = self.agent.classify_followup(text, decision)
        if intent.intent == "cancel":
            return None, None, "Cancelled the pending proposal. Nothing was allocated."
        if intent.intent == "confirm":
            target = next((c for c in decision.candidates if c.workshop_id == intent.workshop_id), None)
            if target is not None:
                try:
                    record = self.confirm(replace(decision, chosen=target), committed_by=requester)
                except ProposalChanged as exc:
                    return exc.decision, None, str(exc)
                return None, record, f"Committed {record.record_id} — {record.order_id} → {record.workshop_id}."
        if any(x in intent.changes for x in ("pieces", "due_date", "other")):
            return None, None, ("This changes the source order. Update the order register and reload the desk first, "
                                "then request a new proposal; nothing has been allocated.")
        # Supply existing constraints on every follow-up, so an explanation or
        # a new objective does not accidentally drop an earlier exclusion.
        context = (f"Current proposal: order {decision.parsed.order_id}; "
                   f"objective {decision.objective}; exclusions {decision.excluded}. "
                   "Preserve these constraints unless the user explicitly changes them. "
                   "For an allocation change, call rank_candidates again.\nUser follow-up: " + text)
        additions = {self.workshops.resolve(x) for x in intent.exclude_add}
        removals = {self.workshops.resolve(x) for x in intent.exclude_remove}
        if None in additions or None in removals:
            return None, None, "Unknown workshop in the changed constraints. Please request a new proposal."
        inherited = {self.workshops.resolve(x) for x in decision.excluded} - removals
        self._ranking_context = {"order_id": decision.parsed.order_id,
                                 "required": sorted((inherited | additions) - {None}),
                                 "removed": removals}
        try:
            updated = self.handle_message(context, requester=requester)
        finally:
            self._ranking_context = None
            _restore_user_text(self.agent, context, text)
        if updated.candidates:
            explicit_ids = {canonical_order_id(x) for x in re.findall(r"\bORD[\s_-]*\d+\b", text, flags=re.I)}
            if (updated.parsed.order_id != decision.parsed.order_id
                    and updated.parsed.order_id not in explicit_ids):
                return None, None, "The response referred to another order. Please specify the order and request a new proposal."
            # Preserve who originally imposed each surviving constraint.
            old_constraints = {self.workshops.resolve(c.target): c
                               for c in decision.parsed.constraints if c.kind == "exclude"}
            updated.parsed.constraints = [
                old_constraints.get(self.workshops.resolve(c.target)) or c
                for c in updated.parsed.constraints]
            return updated, None, updated.explanation
        if intent.intent == "question":
            # A read-only answer can keep the same proposal. Do not change its
            # version: concurrent commits must still trigger a refresh.
            return decision, None, updated.explanation
        return None, None, updated.explanation

    # ---------------- confirmation ----------------

    def confirm(self, decision, committed_by="dispatcher"):
        """The human confirmed: commit the chosen workshop and return the
        audit record. The decision must carry an order and a choice."""
        if decision.chosen is None or not decision.parsed.order_id:
            raise ValueError("nothing to commit: decision has no chosen workshop")
        ids = {c.workshop_id for c in decision.candidates}
        if decision.chosen.workshop_id not in ids:
            raise ValueError("Chosen workshop is not in this proposal")
        if decision.state_version is None:
            raise ValueError("Proposal has no state version. Request a new proposal.")
        if decision.state_version != self.audit.version:
            raise ProposalChanged(self.refresh(decision))
        order = self.orders.by_id(decision.parsed.order_id)
        if order is None:
            raise ValueError("Order no longer exists")
        wid = decision.chosen.workshop_id
        excluded_ids = {self.workshops.resolve(x) for x in decision.excluded}
        if wid in excluded_ids:
            raise ValueError("Workshop is excluded by this proposal")
        error = self.state.validate(order, wid)
        if error:
            raise ValueError(error["error"])
        try:
            return self.audit.allocate(order, self.workshops.workshops[wid],
                committed_by=committed_by, expected_version=decision.state_version,
                decision_id=decision.decision_id,
                evidence={"objective": decision.objective, "excluded": decision.excluded,
                          "constraints": to_dict(decision.parsed.constraints),
                          "reason": decision.explanation, "chosen": to_dict(decision.chosen),
                          "candidates": to_dict(decision.candidates),
                          "tool_log": decision.tool_log})
        except StaleAllocation:
            raise ProposalChanged(self.refresh(decision)) from None

    def confirm_split(self, decision, committed_by="dispatcher"):
        """The human confirmed the split: commit every part (each moves its
        own workshop's queue) in one transaction and return the records."""
        split = decision.split
        if not split or not decision.parsed.order_id:
            raise ValueError("nothing to commit: decision has no split")
        if decision.state_version is None:
            raise ValueError("Proposal has no state version. Request a new proposal.")
        if decision.state_version != self.audit.version:
            raise ProposalChanged(self.refresh(decision))
        order = self.orders.by_id(decision.parsed.order_id)
        if order is None:
            raise ValueError("Order no longer exists")
        ids = [p["workshop_id"] for p in split["parts"]]
        if len(set(ids)) != len(ids):
            raise ValueError("A split must use different workshops")
        excluded_ids = {self.workshops.resolve(x) for x in decision.excluded}
        parts = []
        for part in split["parts"]:
            wid, pieces = part["workshop_id"], int(part["pieces"])
            if wid in excluded_ids:
                raise ValueError(f"{wid} is excluded by this proposal")
            error = self.state.validate({**order, "pieces": pieces}, wid)
            if error:
                raise ValueError(error["error"])
            parts.append((self.workshops.workshops[wid], pieces))
        try:
            return self.audit.allocate_split(order, parts,
                committed_by=committed_by, expected_version=decision.state_version,
                decision_id=decision.decision_id,
                evidence={"objective": decision.objective, "excluded": decision.excluded,
                          "constraints": to_dict(decision.parsed.constraints),
                          "reason": decision.explanation, "split_proposal": split,
                          "candidates": to_dict(decision.candidates),
                          "tool_log": decision.tool_log})
        except StaleAllocation:
            raise ProposalChanged(self.refresh(decision)) from None



if __name__ == "__main__":
    from eval.run_eval import parse_inbox
    req = next(r for r in parse_inbox() if r["request_id"] == "R07")
    desk = DispatchDesk()
    print(f"[R07] {req['speaker']}: {req['text']}\n")
    decision = desk.handle_message(req["text"])
    print(f"behaviour: {decision.behaviour.value}")
    print(f"chosen:    {decision.chosen.workshop_id if decision.chosen else '-'}")
    print(decision.explanation)
