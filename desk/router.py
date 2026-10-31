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
    IMPOSSIBLE  earliest_feasible shows even the split misses the due date;
                v2.2: or a rank whose EVERY candidate finishes late — a
                late recommendation is not an allocation
    ASK         lookup_order returned several matches (ask, don't guess);
                v2.2: or a dispatch-intent message whose tool flow never
                completed (no rank, no feasibility check)
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

# intent signals over the *message text* (never the reply prose): they only
# separate ASK from NO_DATA — the safety cases still read the tool log only
_QUERY_MARKERS = ("did we", "which workshop", "what price", "any movement",
                  "history", "historical", "previously", "last october",
                  "last month", "quote")
_ALLOC_MARKERS = ("send", "sent", "need", "wants", "get ", "moving",
                  "go out", "asap", "reorder", "dispatch", "book", "assign",
                  "urgent", "allocate", "outside")


def _looks_like_data_question(text):
    """Asking about records the data may not hold (R02 history, R13 quotes),
    rather than asking the desk to act. Code over the raw message, so the
    outcome is deterministic."""
    t = (text or "").lower()
    return any(m in t for m in _QUERY_MARKERS) and \
        not any(m in t for m in _ALLOC_MARKERS)


def _looks_like_alloc_request(text):
    """The message wants something dispatched ("send", "need", "asap")
    without being a pure data question. Used to keep half-finished dispatch
    flows out of the ANSWER fallback (v2.2)."""
    t = (text or "").lower()
    return any(m in t for m in _ALLOC_MARKERS) and \
        not any(m in t for m in _QUERY_MARKERS)


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


def candidates_from_rank(result):
    """rank_candidates result -> (candidates, chosen) as contract records."""
    rows = result.get("candidates", [])
    candidates = [Candidate(**{k: row[k] for k in _CANDIDATE_FIELDS})
                  for row in rows]
    chosen = next((c for c in candidates
                   if c.workshop_id == result.get("chosen")), None)
    return candidates, chosen


def _reply_workshop(reply, workshops):
    """The workshop the reply asks the human to commit to ("Reply yes to
    commit ORD-010 to W3"), else the one it says it recommends; None when
    the reply names neither. Only used to keep the structured choice and
    the prose in step — never to decide a behaviour."""
    if workshops is None or not reply:
        return None
    names = {}
    for w in workshops.workshops.values():
        names[w.workshop_id.lower()] = w.workshop_id
        names[w.name.lower()] = w.workshop_id
    shop = "(" + "|".join(re.escape(n) for n in
                          sorted(names, key=len, reverse=True)) + r")\b"
    for pattern in (r"\bcommit\b[^.\n]{0,60}?\bto\s+" + shop,
                    r"\brecommend(?:ed|ation)?(?:\s+(?:is|workshop))?:?\s+" + shop):
        hits = re.findall(pattern, reply.lower())
        if hits:
            return names[hits[-1]]
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
    candidates, chosen, behaviour, options = [], None, Behaviour.ANSWER, []
    warnings = []

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
    #    as the alternatives the reply offers). v2.2: when EVERY candidate
    #    lands after the due date this is not an allocation but an
    #    IMPOSSIBLE — the best-late option still shows as `chosen`.
    if rank_relevant:
        parsed.order_id = parsed.order_id or rank["arguments"].get("order_id")
        rows = rank["result"]["candidates"]
        candidates, top = candidates_from_rank(rank["result"])
        if behaviour is not Behaviour.REFUSE:
            chosen = top
            behaviour = (Behaviour.IMPOSSIBLE
                         if rows and all(r["days_late"] > 0 for r in rows)
                         else Behaviour.ALLOCATE)

    if behaviour is Behaviour.ANSWER:
        # 3. IMPOSSIBLE: even the split misses the due date
        if earliest and not (earliest["result"].get("meets_due_split")
                             or earliest["result"].get("meets_due_single")):
            behaviour = Behaviour.IMPOSSIBLE
        # 4. ASK: several matches — ask which one, never guess; the matches
        #    become tappable options for the UI (guide journey step 6).
        #    A history/quote question stays NO_DATA even when the customer
        #    name resolves to current orders (R02).
        elif lookup and lookup["result"]["status"] == "ambiguous":
            if _looks_like_data_question(text):
                behaviour = Behaviour.NO_DATA
            else:
                behaviour = Behaviour.ASK
                options = [m.get("order_id") for m in lookup["result"]["matches"]
                           if m.get("order_id")]
        # 5. NO_DATA: the message referenced something the data doesn't hold
        elif lookup and lookup["result"]["status"] == "not_found" and (
                requested_id or lookup["arguments"].get("customer")
                or lookup["arguments"].get("product")
                or lookup["arguments"].get("category")):
            behaviour = Behaviour.NO_DATA
        # 6. NO_DATA upgrade: the tools answered fine but the question is
        #    about something outside the data (R13 customer quotes)
        elif _looks_like_data_question(text):
            behaviour = Behaviour.NO_DATA
        # 7. v2.2: a dispatch-intent message whose tool flow never completed
        #    (no rank, no feasibility check) must not fall through to
        #    ANSWER — the desk asks for the missing piece instead
        elif _looks_like_alloc_request(text):
            behaviour = Behaviour.ASK

    # 8. the button must commit what the text recommends: when the reply
    #    asks to commit a different workshop than the ranking chose, follow
    #    the reply if that workshop is a valid candidate, else flag it
    reply_id = _reply_workshop(reply, workshops) if chosen else None
    if reply_id and reply_id != chosen.workshop_id:
        named = next((c for c in candidates if c.workshop_id == reply_id), None)
        if named is not None:
            warnings.append(
                f"The reply recommends {named.name} ({reply_id}) but the ranking "
                f"chose {chosen.name} ({chosen.workshop_id}); the recommendation "
                f"now follows the reply so the button matches the text.")
            chosen = named
        else:
            warnings.append(
                f"The reply recommends {reply_id}, which is not a valid candidate "
                f"for this order; the recommendation stays on "
                f"{chosen.name} ({chosen.workshop_id}). Check before confirming.")

    return Decision(request_id="", behaviour=behaviour, parsed=parsed,
                    candidates=candidates, chosen=chosen,
                    explanation=reply, options=options, tool_log=list(log),
                    warnings=warnings)


if __name__ == "__main__":
    log = [{"tool": "lookup_order", "arguments": {"order_id": "ORD-999"},
            "result": {"status": "not_found", "matches": []}}]
    decision = route("text", "reply", log)
    print(f"behaviour: {decision.behaviour.value}")
    print(f"explanation: {decision.explanation}")
