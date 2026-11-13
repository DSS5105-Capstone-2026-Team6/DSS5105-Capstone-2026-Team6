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
from desk.tools import split_options

# The fixed reply for a cancelled proposal, so adapters can tell "user
# cancelled" apart from "the model answered without re-ranking" (both return
# decision=None, record=None) without matching on wording inline.
CANCEL_REPLY = "Cancelled the pending proposal. Nothing was allocated."

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
                 provider=None, api_key=None, persona="dispatcher", agent=None,
                 as_of=None, storage_dir=None):
        from desk.config import DEFAULT_PROVIDER, set_as_of
        if as_of is not None:
            set_as_of(as_of)   # move the shared world clock (UI world switch)
        self.agent = agent or DispatchAgent(model=model, stages=stages, api_key=api_key,
                                   provider=provider or DEFAULT_PROVIDER,
                                   persona=persona)
        self.agent.desk = self                  # chat loop passes this to tools
        self.orders = OrderStore(stages=stages)
        self.workshops = self.agent.workshops   # shared with the agent
        self.state = DeskState(stages=stages)
        audit_kwargs = {"initial_queues": self.state.queues}
        from desk.performance import PerformanceStore
        if storage_dir is not None:
            # Local sandbox: audit, learned performance and the API budget all
            # live in session-owned SQLite files — nothing in this desk ever
            # touches the shared database (the bot keeps using it).
            from pathlib import Path
            from desk.budget import CallBudget
            d = Path(storage_dir)
            d.mkdir(parents=True, exist_ok=True)
            self.audit = AuditLog(str(d / "audit.sqlite3"), **audit_kwargs)
            self.performance = PerformanceStore(str(d / "performance.sqlite3"))
            self.agent.budget = CallBudget(str(d / "api_usage.sqlite3"))
        else:
            self.audit = AuditLog(audit_path, **audit_kwargs) if audit_path else AuditLog(**audit_kwargs)
            self.performance = PerformanceStore()   # learned shop performance,
                                                    # shared via the ledger db
        self.state.audit = self.audit
        self._version_cache = None   # ledger version; invalidated on our commits

    def _ledger_version(self):
        """audit.version cached per desk: a 30-message dispatch loop used to
        pay one cross-border read per message even though the version only
        moves on commits."""
        if self._version_cache is None:
            self._version_cache = self.audit.version
        return self._version_cache

    # ---------------- conversation ----------------

    def handle_message(self, text, requester=None, request_id=None,
                       verbose=False):
        """One chat message -> Decision (candidates + explanation + tool
        log). No state moves here; that only happens in confirm().
        verbose=True streams each tool round to stdout."""
        version = self._ledger_version()
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
        self._fill_refusal_alternative(decision)
        self._attach_split(decision)
        self._flag_already_committed(decision)
        return decision

    def _flag_already_committed(self, decision):
        """An order already in the ledger cannot be committed again (the
        ledger refuses it), but the model does not read the ledger and may
        still recommend a shop. Keep that ranking for reference, say up
        front that the order is done, and mark the decision so the UI and the
        bot offer a one-tap skip instead of commit buttons."""
        oid = decision.parsed.order_id
        if not oid:
            return
        records = [r for r in self.audit.load_all() if r.order_id == oid]
        if not records:
            return
        shops = " + ".join(r.workshop_id for r in records)
        ids = ", ".join(r.record_id for r in records)
        line = f"{ids} — {oid} → {shops}"
        decision.already_committed = line
        decision.warnings = [f"Already committed: {line}. Committing again is "
                             "refused — skip this request."] + list(decision.warnings)
        decision.explanation = (f"⚠️ {oid} is already committed ({line}); nothing "
                                "more to allocate. The ranking below is for "
                                "reference only — skip this request.\n\n"
                                + (decision.explanation or ""))

    def _fill_refusal_alternative(self, decision):
        """A REFUSE (the named workshop cannot take the order) whose flow
        stopped at check_eligibility has no alternative to offer. Rank the
        eligible workshops in code so the refusal always comes with the best
        alternative ready to commit (the refused shop is ineligible, so the
        ranking never contains it)."""
        oid = decision.parsed.order_id
        if (decision.behaviour is not Behaviour.REFUSE or decision.candidates
                or self.orders.by_id(oid) is None):
            return
        args = {"order_id": oid, "objective": decision.objective,
                "excluded": list(decision.excluded)}
        result = rank_candidates(**args, orders=self.orders, store=self.workshops,
                                 queues=self.state.queues, perf=self.performance)
        if "error" in result or not result.get("candidates"):
            return
        decision.tool_log.append({"tool": "rank_candidates", "arguments": args,
                                  "result": result, "called_by": "desk"})
        decision.candidates, decision.chosen = candidates_from_rank(result)
        best = decision.chosen or decision.candidates[0]
        decision.chosen = best
        decision.explanation = ((decision.explanation or "").rstrip() + "\n\n"
            f"Best eligible alternative ({decision.objective}): {best.name} "
            f"({best.workshop_id}), estimated finish {best.estimated_finish}. "
            f"Reply yes to commit {oid} to {best.workshop_id}.")

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
                                 queues=self.state.queues, perf=self.performance)
        if "error" in result:
            return
        decision.tool_log.append({"tool": "rank_candidates", "arguments": args,
                                  "result": result, "called_by": "desk"})
        decision.candidates, decision.chosen = candidates_from_rank(result)

    def _attach_split(self, decision, force=False):
        """Offer split options (any number of workshops, ranked by the
        proposal's objective exactly like the candidates) that finish
        earlier than the best single batch: always for IMPOSSIBLE, and for
        an ALLOCATE whose flow asked earliest_feasible (e.g. the message
        asked about splitting) or that is a refresh of a proposal which
        already offered splits. Splits live in the chat layer; the
        simulator stays single-batch."""
        oid = decision.parsed.order_id
        asked = force or any(x["tool"] == "earliest_feasible" for x in decision.tool_log)
        decision.splits, decision.recommended_split = [], None
        if (self.orders.by_id(oid) is None
                or decision.behaviour not in (Behaviour.IMPOSSIBLE, Behaviour.ALLOCATE)
                or (decision.behaviour is Behaviour.ALLOCATE and not asked)):
            return
        args = {"order_id": oid, "excluded": list(decision.excluded),
                "objective": decision.objective}
        result = split_options(**args, orders=self.orders, store=self.workshops,
                               queues=self.state.queues, perf=self.performance)
        if "error" in result or not result["options"]:
            return
        decision.tool_log.append({"tool": "split_options", "arguments": args,
                                  "result": result, "called_by": "desk"})
        decision.splits = result["options"]
        if decision.behaviour is Behaviour.IMPOSSIBLE:
            decision.recommended_split = 0      # ranked best, beats any single shop

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
        version = self._ledger_version()
        result = rank_candidates(decision.parsed.order_id, decision.objective,
                                 excluded=decision.excluded, orders=self.orders,
                                 store=self.workshops, queues=self.state.queues,
                                 perf=self.performance)
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
        if decision.behaviour is Behaviour.REFUSE and fresh.candidates:
            # a refusal's alternatives re-ranked on live queues: still a
            # refusal of the named shop, not a fresh ALLOCATE request
            fresh.behaviour = Behaviour.REFUSE
        self._attach_split(fresh, force=bool(decision.splits))
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
            return None, None, CANCEL_REPLY
        if intent.intent == "confirm":
            target = next((c for c in decision.candidates if c.workshop_id == intent.workshop_id), None)
            if target is not None:
                try:
                    record = self.confirm(replace(decision, chosen=target), committed_by=requester)
                except ProposalChanged as exc:
                    return exc.decision, None, str(exc)
                except ValueError as exc:
                    # refused by the checks/ledger (e.g. the order is already
                    # committed): say why, keep the proposal open
                    return decision, None, f"Not committed: {exc}"
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
            self._version_cache = None
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
            record = self.audit.allocate(order, self.workshops.workshops[wid],
                committed_by=committed_by, expected_version=decision.state_version,
                decision_id=decision.decision_id,
                evidence={"objective": decision.objective, "excluded": decision.excluded,
                          "constraints": to_dict(decision.parsed.constraints),
                          "reason": decision.explanation, "chosen": to_dict(decision.chosen),
                          "candidates": to_dict(decision.candidates),
                          "tool_log": decision.tool_log})
            self._version_cache = None        # our commit moved the version
            return record
        except StaleAllocation:
            self._version_cache = None        # someone else moved it
            raise ProposalChanged(self.refresh(decision)) from None

    def confirm_all(self, decisions, committed_by="dispatcher"):
        """Commit every given proposal's chosen workshop, one audited
        transaction per order — per-order validation (version, eligibility,
        duplicates) is fully intact, this only saves the human N-1 clicks.

        A commit bumps the ledger version, so the NEXT proposal is stale by
        construction: on ProposalChanged we confirm the refreshed decision it
        carries (same order, live numbers). Returns (results, failures) —
        results are (decision, record) pairs, failures are (order_id, reason)
        and never stop the batch."""
        results, failures = [], []
        for d in decisions:
            oid = d.parsed.order_id or "?"
            try:
                try:
                    results.append((d, self.confirm(d, committed_by=committed_by)))
                except ProposalChanged as exc:
                    results.append((d, self.confirm(exc.decision,
                                                    committed_by=committed_by)))
            except (ProposalChanged, ValueError) as exc:
                failures.append((oid, str(exc)))
        return results, failures

    def confirm_split(self, decision, index=0, committed_by="dispatcher"):
        """The human confirmed split option `index`: commit every part (each
        moves its own workshop's queue) in one transaction and return the
        records."""
        if not decision.parsed.order_id or not 0 <= index < len(decision.splits):
            raise ValueError("nothing to commit: decision has no such split")
        split = decision.splits[index]
        if decision.state_version is None:
            raise ValueError("Proposal has no state version. Request a new proposal.")
        if decision.state_version != self.audit.version:
            self._version_cache = None
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
            records = self.audit.allocate_split(order, parts,
                committed_by=committed_by, expected_version=decision.state_version,
                decision_id=decision.decision_id,
                evidence={"objective": decision.objective, "excluded": decision.excluded,
                          "constraints": to_dict(decision.parsed.constraints),
                          "reason": decision.explanation, "split_proposal": split,
                          "candidates": to_dict(decision.candidates),
                          "tool_log": decision.tool_log})
            self._version_cache = None
            return records
        except StaleAllocation:
            self._version_cache = None
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
