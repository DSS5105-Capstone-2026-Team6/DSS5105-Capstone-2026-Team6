"""
tools — the deterministic tool layer the LLM calls through.

The seven core tools (roadmap Table 4) live here with their JSON schemas;
rank_candidates (the allocator) is implemented in desk/allocator.py and
exposed through the same registry. TOOL_REGISTRY maps each tool to its
schema (sent to the model) and its Python function (executed locally, no
LLM). dispatch_tool() is the single entry point: it resolves the shared
stores from the desk context when one is given, so tools and simulator
always read the same data.

Tool index:
    lookup_order        resolve the order a chat message refers to
    check_eligibility   per-workshop eligible yes/no, with the reason
    get_queue           queue snapshot (as of 2026-04-01)
    estimate_delivery   finish date, slack, cost, defect risk (one order x workshop)
    probe_overload      read-only what-if overload probe
    earliest_feasible   earliest date, single batch or split
    commit_allocation   audited commit (re-checks eligibility first)
    rank_candidates     the allocator (desk/allocator.py)
"""

from datetime import date, datetime, timedelta

try:
    from desk.register import OrderStore, WorkshopStore
    from desk.allocator import rank_candidates, RANK_CANDIDATES_SCHEMA
    from desk.contracts import AllocationRecord, to_dict
except ImportError:  # run directly as a script: python desk/tools.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.register import OrderStore, WorkshopStore
    from desk.allocator import rank_candidates, RANK_CANDIDATES_SCHEMA
    from desk.contracts import AllocationRecord, to_dict

# algorithm2.py is a script-style module (imports `simulate` flat), so its
# directory must be importable whether we run as a package or directly.
import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import est_turnaround_expected
from harness.simulate import eligible_workshops, remaining_stages

CHAT_TODAY = date(2026, 4, 1)
CHAT_AS_OF = "2026-04-01"


# ---------------- lookup_order ----------------

def lookup_order(order_id=None, customer=None, product=None, category=None,
                 *, store=None):
    """Resolve an order. Returns {"status", "matches", "message"}.

    status: "found" (exactly one), "ambiguous" (several — ask, don't guess),
    "not_found" (none — never a nearest match).
    """
    store = store or OrderStore()

    if order_id:
        rec = store.by_id(order_id)
        if rec is None:
            return {"status": "not_found", "matches": [],
                    "message": f"No order with id {order_id} exists in orders.csv."}
        return {"status": "found", "matches": [store.row(rec)],
                "message": f"Found {order_id}."}

    if customer is None and product is None and category is None:
        return {"status": "not_found", "matches": [],
                "message": "No order_id or filters given; ask for the order id, "
                           "customer, product or category."}

    matches = store.orders
    if customer:
        matches = [r for r in matches if customer.lower() in r["customer"].lower()]
    if product:
        matches = [r for r in matches if product.lower() in r["product"].lower()]
    if category:
        matches = [r for r in matches if r["category"] == category.upper()]

    if not matches:
        return {"status": "not_found", "matches": [],
                "message": "No order matches those filters."}
    rows = [store.row(r) for r in matches]
    if len(rows) == 1:
        return {"status": "found", "matches": rows,
                "message": f"Found {rows[0]['order_id']}."}
    return {"status": "ambiguous", "matches": rows,
            "message": f"{len(rows)} orders match; ask which one is meant."}


LOOKUP_ORDER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lookup_order",
        "description": "Resolve the order a chat message refers to, by exact "
                       "order id or by customer/product/category filters. "
                       "Returns all matches; several matches means ask the "
                       "dispatcher which one is meant.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string",
                             "description": "Exact id, e.g. ORD-073"},
                "customer": {"type": "string",
                             "description": "Customer name (substring, case-insensitive)"},
                "product": {"type": "string",
                            "description": "Product name (substring, case-insensitive)"},
                "category": {"type": "string", "enum": ["TOPS", "ACCESSORIES"],
                             "description": "Product category"},
            },
            "required": [],
        },
    },
}


# ---------------- check_eligibility ----------------

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


# ---------------- get_queue ----------------

def get_queue(workshop_ids=None, *, store=None, queues=None):
    """Queue snapshot for the given workshops (all of them by default).
    Unknown names land in "unknown" instead of failing silently. `queues`
    supplies the live chat-side state; recent_change is the drift from the
    2026-04-01 snapshot caused by commits."""
    store = store or WorkshopStore()
    queues = queues or {wid: w.queue0 for wid, w in store.workshops.items()}

    ids, unknown = [], []
    if workshop_ids:
        for name in workshop_ids:
            wid = store.resolve(name)
            (ids.append(wid) if wid else unknown.append(name))
    else:
        ids = list(store.workshops)

    rows = []
    for wid in ids:
        w = store.workshops[wid]
        rows.append({"workshop_id": w.workshop_id, "name": w.name,
                     "queue_days": round(queues[wid], 2),
                     "recent_change": round(queues[wid] - w.queue0, 2)})
    result = {"as_of": CHAT_AS_OF, "source": "live chat-side queues (2026-04-01 snapshot + commits)",
              "workshops": rows}
    if unknown:
        result["unknown"] = unknown
    return result


GET_QUEUE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_queue",
        "description": "Days of work each workshop is currently holding "
                       "(the 2026-04-01 queue snapshot). Call it whenever "
                       "a request mentions speed, capacity or room this week.",
        "parameters": {
            "type": "object",
            "properties": {
                "workshop_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "workshop names or ids "
                                                "(omit for all eight)"},
            },
            "required": [],
        },
    },
}


# ---------------- estimate_delivery ----------------

def estimate_delivery(order_id=None, workshop_id=None, *,
                      orders=None, store=None, queues=None):
    """Estimate one order at one workshop. Returns an error dict for unknown
    ids — never a nearest match, mirroring lookup_order's guard. `queues`
    overrides the 1 April snapshot with the desk's live chat-side queues."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    queues = queues or {wid2: w2.queue0 for wid2, w2 in store.workshops.items()}
    if not order_id:
        return {"error": "order_id is required"}
    if not workshop_id:
        return {"error": "workshop_id is required"}

    rec = orders.by_id(order_id)
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}
    wid = store.resolve(workshop_id)
    if wid is None:
        return {"error": f"unknown workshop {workshop_id!r}"}
    w = store.workshops[wid]

    pieces = int(rec["pieces"])
    due_date = date.fromisoformat(rec["due_date"])
    batch = {"category": rec["category"], "pieces": pieces,
             "sent_date": CHAT_TODAY, "due_date": due_date}

    total_days = est_turnaround_expected(batch, w, queues)
    finish = CHAT_TODAY + timedelta(days=round(total_days))
    work_days = pieces / w.capacity * (1 + 0.5 * w.defect_rate)

    return {"order_id": order_id, "workshop_id": wid, "workshop_name": w.name,
            "estimated_finish": finish.isoformat(),
            "days_late": max(0, (finish - due_date).days),
            "slack_days": (due_date - finish).days,
            "cost": round(pieces * w.cost, 2),
            "defect_risk": w.defect_rate,
            "estimator": "profile_card",
            "as_of": CHAT_TODAY.isoformat(),
            "components": {"queue_days": round(queues[wid], 2),
                           "work_days_expected": round(work_days, 2),
                           "transport_days": w.lead_days}}


ESTIMATE_DELIVERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "estimate_delivery",
        "description": "Estimated finish date, slack against the due date, "
                       "cost and defect risk for one order at one workshop. "
                       "Call it for every candidate before recommending.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "e.g. ORD-073"},
                "workshop_id": {"type": "string",
                                "description": "workshop name or id"},
            },
            "required": ["order_id", "workshop_id"],
        },
    },
}


# ---------------- probe_overload ----------------

def probe_overload(workshop_id=None, additional_pieces=None, *,
                   store=None, queues=None):
    """Read-only overload probe. Error dicts for unknown workshop or bad
    piece counts — never a silent guess. `queues` overrides the snapshot
    with the desk's live chat-side queues."""
    store = store or WorkshopStore()
    queues = queues or {i: w.queue0 for i, w in store.workshops.items()}
    if not workshop_id:
        return {"error": "workshop_id is required"}
    wid = store.resolve(workshop_id)
    if wid is None:
        return {"error": f"unknown workshop {workshop_id!r}"}
    if not isinstance(additional_pieces, int) or additional_pieces <= 0:
        return {"error": f"additional_pieces must be a positive integer, "
                         f"got {additional_pieces!r}"}

    w = store.workshops[wid]
    current = queues[wid]
    # expected added work = algorithm2's priced formula, derived from
    # est_turnaround_expected itself (queue 0, transport subtracted) so the
    # single source of truth stays in the harness.
    zero_queues = {i: 0.0 for i in store.workshops}
    batch = {"category": "TOPS", "pieces": additional_pieces,
             "sent_date": None, "due_date": None}
    added = est_turnaround_expected(batch, w, zero_queues) - w.lead_days
    # simulator's defective case: work is redone at 1.5x (simulate.py:245)
    defective_added = additional_pieces / w.capacity * 1.5
    return {"workshop_id": wid, "name": w.name,
            "current_queue_days": round(current, 2),
            "added_work_days_expected": round(added, 2),
            "new_queue_days_expected": round(current + added, 2),
            # first-come-first-served: the new batch goes to the back, so
            # everything already queued slips by exactly the added work
            "delay_to_queued_orders_days": round(added, 2),
            "defective_case": {
                "added_work_days_if_defective": round(defective_added, 2),
                "new_queue_days_if_defective": round(current + defective_added, 2),
                "delay_if_defective": round(defective_added, 2)},
            "read_only": True}


PROBE_OVERLOAD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "probe_overload",
        "description": "What happens to a workshop's queue if it takes more "
                       "pieces: the new queue length and the delay imposed on "
                       "orders already queued. Read-only; call it when a "
                       "request risks overloading a workshop.",
        "parameters": {
            "type": "object",
            "properties": {
                "workshop_id": {"type": "string",
                                "description": "workshop name or id"},
                "additional_pieces": {"type": "integer"},
            },
            "required": ["workshop_id", "additional_pieces"],
        },
    },
}


# ---------------- earliest_feasible ----------------

def _eligible_for(pieces, category, store):
    """Eligible workshops for a part of this size — the simulator's own
    rule, so per-part eligibility can never drift from the rest."""
    batch = {"category": category, "pieces": pieces}
    return eligible_workshops(batch, store.workshops)


def _finish(pieces, w, queues):
    batch = {"pieces": pieces}
    return est_turnaround_expected(batch, w, queues)


def earliest_feasible(order_id=None, *, orders=None, store=None, queues=None):
    """Earliest date as one batch and as a two-way split. Error dict for an
    unknown order; flags report when even the split misses the due date.
    `queues` overrides the 1 April snapshot with live chat-side queues."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    queues = queues or {wid: w.queue0 for wid, w in store.workshops.items()}
    rec = orders.by_id(order_id) if order_id else None
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}

    pieces, category = int(rec["pieces"]), rec["category"]
    due = date.fromisoformat(rec["due_date"])

    # --- single batch: earliest finish over all eligible workshops
    single = None   # (finish date, workshop)
    for w in _eligible_for(pieces, category, store):
        finish = CHAT_TODAY + timedelta(days=round(_finish(pieces, w, queues)))
        if single is None or finish < single[0]:
            single = (finish, w)

    # --- split across two different workshops, every size combination
    best_split = None
    elig_cache = {}

    def elig(n):
        if n not in elig_cache:
            elig_cache[n] = _eligible_for(n, category, store)
        return elig_cache[n]

    for a in range(1, pieces):
        b = pieces - a
        for w1 in elig_cache.setdefault(a, _eligible_for(a, category, store)):
            f1 = _finish(a, w1, queues)
            for w2 in elig_cache.setdefault(b, _eligible_for(b, category, store)):
                if w2.workshop_id == w1.workshop_id:
                    continue            # same shop = serial, no parallelism
                f2 = _finish(b, w2, queues)
                finish = CHAT_TODAY + timedelta(days=round(max(f1, f2)))
                if best_split is None or finish < best_split[0]:
                    best_split = (finish, w1, a, w2, b)

    def _slack(finish_iso):
        return (due - date.fromisoformat(finish_iso)).days if finish_iso else None

    single_out = ({"earliest_finish": single[0].isoformat(),
                   "workshop_id": single[1].workshop_id, "name": single[1].name}
                  if single else None)
    split_out = ({"earliest_finish": best_split[0].isoformat(),
                  "parts": [{"workshop_id": best_split[1].workshop_id,
                             "name": best_split[1].name, "pieces": best_split[2]},
                            {"workshop_id": best_split[3].workshop_id,
                             "name": best_split[3].name, "pieces": best_split[4]}]}
                 if best_split else None)

    return {"order_id": order_id, "due_date": due.isoformat(),
            "single": single_out, "split": split_out,
            "meets_due_single": bool(single_out and single_out["earliest_finish"] <= due.isoformat()),
            "meets_due_split": bool(split_out and split_out["earliest_finish"] <= due.isoformat()),
            "slack_days_single": _slack(single_out and single_out["earliest_finish"]),
            "slack_days_split": _slack(split_out and split_out["earliest_finish"]),
            "advisory": "splits are advisory; the simulator sends one batch "
                        "to one workshop (roadmap, Assumption 4)"}


EARLIEST_FEASIBLE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "earliest_feasible",
        "description": "Earliest achievable delivery date for an order — as "
                       "one batch and split across two shops. Use it for "
                       "impossible-looking dates and when a request asks "
                       "about splitting.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
}


# ---------------- commit_allocation ----------------

def commit_allocation(order_id=None, workshop_id=None,
                      committed_by="dispatcher", *, orders=None, desk=None):
    """Confirm an allocation: re-check eligibility, move the chat-side
    queue, append the audit record. Returns {"committed": True, "record"}
    or {"committed": False, "error"} — never a silent write."""
    if desk is None:
        return {"committed": False,
                "error": "commit_allocation needs a desk context (state + audit)"}
    orders = orders or desk.orders
    if not order_id or not workshop_id:
        return {"committed": False,
                "error": "order_id and workshop_id are required"}
    rec = orders.by_id(order_id)
    if rec is None:
        return {"committed": False, "error": f"unknown order {order_id!r}"}
    wid = desk.workshops.resolve(workshop_id)
    if wid is None:
        return {"committed": False, "error": f"unknown workshop {workshop_id!r}"}

    result = desk.state.commit(rec, wid)
    if isinstance(result, dict):                    # eligibility re-check failed
        return {"committed": False, **result}
    queue_before, queue_after = result

    record = AllocationRecord(
        record_id=f"A-{len(desk.audit.load_all()) + 1:04d}",
        decision_id=order_id, order_id=order_id, workshop_id=wid,
        pieces=int(rec["pieces"]), committed_by=committed_by,
        committed_at=datetime.now().isoformat(timespec="seconds"),
        queue_before=round(queue_before, 2), queue_after=round(queue_after, 2))
    desk.audit.append(record)
    return {"committed": True, "record": to_dict(record)}


COMMIT_ALLOCATION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "commit_allocation",
        "description": "Commit an allocation after the human dispatcher "
                       "confirms: re-checks eligibility, updates the queue "
                       "and writes the append-only audit record. Never call "
                       "it without an explicit confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "workshop_id": {"type": "string"},
                "committed_by": {"type": "string",
                                 "description": "who confirmed"},
            },
            "required": ["order_id", "workshop_id"],
        },
    },
}


# ---------------- registry ----------------

TOOL_REGISTRY = {
    "lookup_order": {"schema": LOOKUP_ORDER_SCHEMA, "func": lookup_order},
    "check_eligibility": {"schema": CHECK_ELIGIBILITY_SCHEMA,
                          "func": check_eligibility},
    "get_queue": {"schema": GET_QUEUE_SCHEMA, "func": get_queue},
    "estimate_delivery": {"schema": ESTIMATE_DELIVERY_SCHEMA,
                          "func": estimate_delivery},
    "rank_candidates": {"schema": RANK_CANDIDATES_SCHEMA,
                        "func": rank_candidates},
    "probe_overload": {"schema": PROBE_OVERLOAD_SCHEMA, "func": probe_overload},
    "earliest_feasible": {"schema": EARLIEST_FEASIBLE_SCHEMA,
                          "func": earliest_feasible},
    "commit_allocation": {"schema": COMMIT_ALLOCATION_SCHEMA,
                          "func": commit_allocation},
}

# which store each kwarg receives ("orders" = OrderStore, "workshops" =
# WorkshopStore); lookup_order's kwarg is named "store" but holds orders
_STORE_KWARGS = {
    "lookup_order": {"store": "orders"},
    "check_eligibility": {"store": "workshops"},
    "get_queue": {"store": "workshops"},
    "estimate_delivery": {"orders": "orders", "store": "workshops"},
    "rank_candidates": {"orders": "orders", "store": "workshops"},
    "earliest_feasible": {"orders": "orders", "store": "workshops"},
}
_FACTORIES = {"orders": OrderStore, "workshops": WorkshopStore}

# tools that accept a `queues` override: with a desk they read its live
# chat-side queues (commits move later answers); without one they fall back
# to the 2026-04-01 snapshot inside the tool
_QUEUES_TOOLS = {"get_queue", "estimate_delivery", "rank_candidates",
                 "probe_overload", "earliest_feasible"}


def tool_schemas():
    """The schemas to pass as `tools=` to the chat completion."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]


def dispatch_tool(name, arguments, *, desk=None):
    """Execute one tool call from the model. Returns the tool's result dict
    (or an error dict the model can read and relay). With a desk, tools read
    its shared stores and live queues, and commit_allocation can write state;
    without one, fresh stores are built and the committer refuses (nothing
    to commit to)."""
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": f"unknown tool {name!r}"}
    kwargs = dict(arguments or {})
    if name == "commit_allocation":
        kwargs["orders"] = desk.orders if desk else None
        kwargs["desk"] = desk
    else:
        for param, kind in _STORE_KWARGS.get(name, {}).items():
            if desk is not None:
                kwargs[param] = getattr(desk, kind)
            else:
                kwargs[param] = _FACTORIES[kind]()
        if desk is not None and name in _QUEUES_TOOLS:
            kwargs["queues"] = desk.state.queues
    try:
        return entry["func"](**kwargs)
    except (TypeError, ValueError) as exc:
        return {"error": f"bad arguments for {name}: {exc}"}


if __name__ == "__main__":
    print(f"{len(TOOL_REGISTRY)} tools registered (all implemented):")
    for name in TOOL_REGISTRY:
        print(f"  {name}")
    print("\nsample dispatch:")
    print(dispatch_tool("lookup_order", {"order_id": "ORD-063"}))
