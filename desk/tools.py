"""
tools — the deterministic tool layer the LLM calls through.

The read-only tools live here with their JSON schemas;
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
    update_workshop_performance  learn from returned batches (roadmap §1.6)
    flag_at_risk        committed batches projected to miss their due date
    commit_allocation   backend-only compatibility endpoint; not a model tool
    rank_candidates     the allocator (desk/allocator.py)
"""

from datetime import date, timedelta
import itertools
import math

try:
    from desk.register import OrderStore, WorkshopStore
    from desk.allocator import rank_candidates, RANK_CANDIDATES_SCHEMA
    from desk.contracts import to_dict
    from desk.performance import PerformanceStore, MIN_SAMPLES
    from desk.config import CHAT_AS_OF
except ImportError:  # run directly as a script: python desk/tools.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.register import OrderStore, WorkshopStore
    from desk.allocator import rank_candidates, RANK_CANDIDATES_SCHEMA
    from desk.contracts import to_dict
    from desk.performance import PerformanceStore, MIN_SAMPLES
    from desk.config import CHAT_AS_OF

# algorithm2.py is a script-style module (imports `simulate` flat), so its
# directory must be importable whether we run as a package or directly.
import sys
from pathlib import Path as _Path
_HARNESS = str(_Path(__file__).parent.parent / "harness")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
from harness.algorithm2 import est_turnaround_expected
from harness.simulate import eligible_workshops, remaining_stages

CHAT_TODAY = date.fromisoformat(CHAT_AS_OF)


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
                "message": f"Found {rec['order_id']}."}

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
                      orders=None, store=None, queues=None, perf=None):
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

    # learned performance (roadmap §1.6): once MIN_SAMPLES returned batches
    # are on file, the estimate runs on the workshop's effective capacity and
    # lead time instead of the profile card
    learned = perf.learned(wid, profile=w) if perf else None
    if learned:
        work_days = pieces / learned["eff_capacity"] * (1 + 0.5 * w.defect_rate)
        total_days = queues[wid] + work_days + learned["eff_lead_days"]
    else:
        total_days = est_turnaround_expected(batch, w, queues)
        work_days = pieces / w.capacity * (1 + 0.5 * w.defect_rate)
    finish = CHAT_TODAY + timedelta(days=round(total_days))

    out = {"order_id": order_id, "workshop_id": wid, "workshop_name": w.name,
           "estimated_finish": finish.isoformat(),
           "days_late": max(0, (finish - due_date).days),
           "slack_days": (due_date - finish).days,
           "cost": round(pieces * w.cost, 2),
           "defect_risk": w.defect_rate,
           "estimator": "learned" if learned else "profile_card",
           "as_of": CHAT_TODAY.isoformat(),
           "components": {"queue_days": round(queues[wid], 2),
                          "work_days_expected": round(work_days, 2),
                          "transport_days": learned["eff_lead_days"] if learned
                          else w.lead_days}}
    # cautious estimate: the date the workshop meets in ~80% of observed
    # batches, surfaced only when slack is tight (roadmap Table 5)
    if learned and 0 <= out["slack_days"] <= 2:
        cautious = CHAT_TODAY + timedelta(days=round(total_days
                                                     + learned["p80_delay"]))
        out["cautious"] = {"finish_p80": cautious.isoformat(),
                           "p80_delay_days": learned["p80_delay"],
                           "note": "tight slack: this workshop's 80th-"
                                   "percentile delay puts the finish here"}
    return out


ESTIMATE_DELIVERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "estimate_delivery",
        "description": "Estimated finish date, slack against the due date, "
                       "cost and defect risk for one order at one workshop. "
                       "Use it to double-check a single named workshop; to "
                       "compare workshops or pick one, call rank_candidates "
                       "instead — never estimate workshops one by one.",
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

def _eligible_for(pieces, category, store, excluded_ids=frozenset()):
    """Eligible workshops for a part of this size — the simulator's own
    rule, so per-part eligibility can never drift from the rest."""
    batch = {"category": category, "pieces": pieces}
    return [w for w in eligible_workshops(batch, store.workshops)
            if w.workshop_id not in excluded_ids]


def _finish(pieces, w, queues):
    batch = {"pieces": pieces}
    return est_turnaround_expected(batch, w, queues)


def earliest_feasible(order_id=None, excluded=None, *, orders=None, store=None,
                      queues=None):
    """Earliest date as one batch and as a two-way split. Error dict for an
    unknown order; flags report when even the split misses the due date.
    `queues` overrides the 1 April snapshot with live chat-side queues;
    `excluded` workshops (names or ids) are left out of both."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    queues = queues or {wid: w.queue0 for wid, w in store.workshops.items()}
    rec = orders.by_id(order_id) if order_id else None
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}
    excluded_ids = set()
    for name in excluded or []:
        wid = store.resolve(name)
        if not wid:
            return {"error": f"unknown excluded workshop {name!r}"}
        excluded_ids.add(wid)

    pieces, category = int(rec["pieces"]), rec["category"]
    due = date.fromisoformat(rec["due_date"])

    # --- single batch: earliest finish over all eligible workshops
    single = None   # (finish date, workshop)
    for w in _eligible_for(pieces, category, store, excluded_ids):
        finish = CHAT_TODAY + timedelta(days=round(_finish(pieces, w, queues)))
        if single is None or finish < single[0]:
            single = (finish, w)

    # --- split across two different workshops, every size combination
    best_split = None
    elig_cache = {}

    def elig(n):
        if n not in elig_cache:
            elig_cache[n] = _eligible_for(n, category, store, excluded_ids)
        return elig_cache[n]

    for a in range(1, pieces):
        b = pieces - a
        for w1 in elig(a):
            f1 = _finish(a, w1, queues)
            for w2 in elig(b):
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
            "excluded": sorted(excluded_ids),
            "advisory": "a split can be confirmed in the chat desk (both parts "
                        "are committed); the simulator still sends one batch "
                        "to one workshop (roadmap, Assumption 4)"}


def _best_split_for(shops, pieces, category, store, queues, min_part=1):
    """Earliest finish when `pieces` are shared over exactly these shops,
    all working in parallel. Searches the finish time T: by T each shop can
    finish floor((T - queue - lead) * capacity / (1 + 0.5 * defect_rate))
    pieces (capped at max_batch), and the earliest T at which the shops
    cover the order, with at least `min_part` pieces each, is optimal.
    None when the shops cannot cover it."""
    rate = {w.workshop_id: w.capacity / (1 + 0.5 * w.defect_rate) for w in shops}
    start = {w.workshop_id: queues[w.workshop_id] + w.lead_days for w in shops}

    def can_make(w, t):
        n = math.floor((t - start[w.workshop_id]) * rate[w.workshop_id] + 1e-9)
        return max(0, min(n, w.max_batch or pieces))

    if (sum(can_make(w, 1e9) for w in shops) < pieces
            or min(can_make(w, 1e9) for w in shops) < min_part):
        return None
    lo, hi = 0.0, max(start.values()) + pieces / min(rate.values()) + 1
    for _ in range(60):
        mid = (lo + hi) / 2
        made = [can_make(w, mid) for w in shops]
        if sum(made) >= pieces and min(made) >= min_part:
            hi = mid
        else:
            lo = mid
    split = {w.workshop_id: can_make(w, hi) for w in shops}
    excess = sum(split.values()) - pieces
    while excess > 0:   # hand back the surplus from the latest-finishing part
        w = max((w for w in shops if split[w.workshop_id] > min_part),
                key=lambda w: _finish(split[w.workshop_id], w, queues))
        cut = min(excess, split[w.workshop_id] - min_part)
        split[w.workshop_id] -= cut
        excess -= cut
    for w in shops:     # every part must itself be eligible (e.g. batch caps)
        if w not in _eligible_for(split[w.workshop_id], category, store):
            return None
    return split


def split_options(order_id=None, excluded=None, max_shops=None, top=5,
                  min_part_share=0.1, *, orders=None, store=None, queues=None):
    """Every way to split an order over two or more workshops (no ceiling
    unless `max_shops` is given; at most 7 eligible shops = 120 sets), each set
    with its best piece split, ranked by days late, then earliest finish,
    then fewer shops, then cost. A split is kept only when it finishes
    earlier than the best single batch and than every split over a subset
    of its shops (an extra shop must earn its pickup and QC), and each part
    carries at least `min_part_share` of the order (no 1-piece parts).
    Chat layer only: the simulator still sends one batch to one workshop."""
    orders = orders or OrderStore()
    store = store or WorkshopStore()
    queues = queues or {wid: w.queue0 for wid, w in store.workshops.items()}
    rec = orders.by_id(order_id) if order_id else None
    if rec is None:
        return {"error": f"unknown order {order_id!r}"}
    excluded_ids = set()
    for name in excluded or []:
        wid = store.resolve(name)
        if not wid:
            return {"error": f"unknown excluded workshop {name!r}"}
        excluded_ids.add(wid)

    pieces, category = int(rec["pieces"]), rec["category"]
    due = date.fromisoformat(rec["due_date"])
    single = min((_finish(pieces, w, queues)
                  for w in _eligible_for(pieces, category, store, excluded_ids)),
                 default=None)
    single_finish = (CHAT_TODAY + timedelta(days=round(single))) if single is not None else None
    shops = _eligible_for(1, category, store, excluded_ids)
    min_part = max(1, math.ceil(pieces * min_part_share))

    options = []
    for k in range(2, min(max_shops or len(shops), len(shops)) + 1):
        for group in itertools.combinations(shops, k):
            split = _best_split_for(group, pieces, category, store, queues, min_part)
            if split is None:
                continue
            days = max(_finish(split[w.workshop_id], w, queues) for w in group)
            finish = CHAT_TODAY + timedelta(days=round(days))
            if single_finish is not None and finish >= single_finish:
                continue
            options.append({
                "parts": [{"workshop_id": w.workshop_id, "name": w.name,
                           "pieces": split[w.workshop_id]} for w in group],
                "n_shops": k,
                "earliest_finish": finish.isoformat(),
                "est_finish_days": round(days, 2),
                "days_late": max(0, (finish - due).days),
                "meets_due": finish <= due,
                "cost": round(sum(split[w.workshop_id] * w.cost for w in group), 2),
                "defect_risk": round(sum(split[w.workshop_id] * w.defect_rate
                                         for w in group) / pieces, 4)})
    def shop_set(o):
        return {p["workshop_id"] for p in o["parts"]}
    options = [o for o in options
               if not any(shop_set(x) < shop_set(o)
                          and x["est_finish_days"] <= o["est_finish_days"]
                          for x in options)]
    options.sort(key=lambda o: (o["days_late"], o["est_finish_days"],
                                o["n_shops"], o["cost"]))
    return {"order_id": order_id, "due_date": due.isoformat(),
            "single_finish": single_finish and single_finish.isoformat(),
            "excluded": sorted(excluded_ids), "options": options[:top],
            "n_options": len(options),
            "advisory": "chat-layer splits; the simulator still sends one "
                        "batch to one workshop"}


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
                "excluded": {"type": "array", "items": {"type": "string"},
                             "description": "workshops the request excludes"},
            },
            "required": ["order_id"],
        },
    },
}


# ---------------- update_workshop_performance ----------------

def update_workshop_performance(workshop_id=None, pieces=None,
                                promised_date=None, actual_date=None, *,
                                store=None, perf=None):
    """Record one returned batch and update the workshop's learned
    performance (roadmap Table 4). Read-only for allocations: it only makes
    future estimates more accurate, it never moves work."""
    store = store or WorkshopStore()
    perf = perf or PerformanceStore()
    if not workshop_id:
        return {"error": "workshop_id is required"}
    wid = store.resolve(workshop_id)
    if wid is None:
        return {"error": f"unknown workshop {workshop_id!r}"}
    if not isinstance(pieces, int) or pieces <= 0:
        return {"error": f"pieces must be a positive integer, got {pieces!r}"}
    try:
        result = perf.observe(wid, pieces, promised_date, actual_date)
    except (TypeError, ValueError) as exc:
        return {"error": f"bad dates (expected ISO YYYY-MM-DD): {exc}"}
    if not result["active"]:
        result["note"] = (f"recorded; learned estimates activate after "
                          f"{MIN_SAMPLES} observed batches (currently "
                          f"{result['observations']}) — profile card in use")
    else:
        result["note"] = ("learned estimates active: effective capacity "
                          f"{result.get('eff_capacity')} pcs/day, p80 delay "
                          f"{result.get('p80_delay')}d")
    return result


UPDATE_WORKSHOP_PERFORMANCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_workshop_performance",
        "description": "Record a returned batch (promised vs actual date) so "
                       "the workshop's estimates learn from reality. Call it "
                       "whenever a message reports a batch came back. Does "
                       "not change any allocation.",
        "parameters": {
            "type": "object",
            "properties": {
                "workshop_id": {"type": "string",
                                "description": "workshop name or id"},
                "pieces": {"type": "integer"},
                "promised_date": {"type": "string",
                                  "description": "ISO YYYY-MM-DD"},
                "actual_date": {"type": "string",
                                "description": "ISO YYYY-MM-DD"},
            },
            "required": ["workshop_id", "pieces", "promised_date",
                         "actual_date"],
        },
    },
}


# ---------------- flag_at_risk ----------------

def flag_at_risk(*, desk=None):
    """Read-only early warning: every committed batch whose projected finish
    (from the live queues) now lands after its due date. Never moves a batch;
    reassignment remains a human decision (roadmap Table 4)."""
    if desk is None:
        return {"error": "flag_at_risk needs a desk context (audit + queues)"}
    at_risk = []
    for rec in desk.audit.load_all():
        order = desk.orders.by_id(rec.order_id)
        if order is None:
            continue
        due = date.fromisoformat(order["due_date"])
        committed = date.fromisoformat(rec.committed_at[:10])
        w = desk.workshops.workshops[rec.workshop_id]
        work = rec.pieces / w.capacity * (1 + 0.5 * w.defect_rate)
        # projection: the batch sat behind queue_before days of work at
        # commit; elapsed days since commit drain it day by day. The ledger
        # records wall-clock time while the desk world sits at CHAT_TODAY,
        # so a real-time timestamp lands "after" the world — clamp at 0.
        elapsed = max(0, (CHAT_TODAY - committed).days)
        remaining = max(0.0, rec.queue_before + work + w.lead_days - elapsed)
        projected = CHAT_TODAY + timedelta(days=round(remaining))
        if projected > due:
            at_risk.append({
                "order_id": rec.order_id, "record_id": rec.record_id,
                "workshop_id": rec.workshop_id, "workshop_name": w.name,
                "due_date": due.isoformat(),
                "projected_finish": projected.isoformat(),
                "projected_days_late": (projected - due).days})
    at_risk.sort(key=lambda r: -r["projected_days_late"])
    return {"as_of": CHAT_AS_OF, "at_risk": at_risk, "n_at_risk": len(at_risk),
            "options": ["wait", "split the remainder", "reassign",
                        "escalate"],
            "read_only": True,
            "note": "reassignment requires human confirmation; nothing here "
                    "moves a batch"}


FLAG_AT_RISK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "flag_at_risk",
        "description": "List committed batches now projected to miss their "
                       "due date, with options (wait / split the remainder / "
                       "reassign / escalate). Read-only early warning; call "
                       "it when asked about risks, delays or anything "
                       "slipping.",
        "parameters": {"type": "object", "properties": {}},
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

    error = desk.state.validate(rec, wid)
    if error:
        return {"committed": False, **error}
    try:
        record = desk.audit.allocate(rec, desk.workshops.workshops[wid],
                                     committed_by=committed_by)
    except ValueError as exc:
        return {"committed": False, "error": str(exc)}
    return {"committed": True, "record": to_dict(record)}



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
    "update_workshop_performance": {"schema": UPDATE_WORKSHOP_PERFORMANCE_SCHEMA,
                                    "func": update_workshop_performance},
    "flag_at_risk": {"schema": FLAG_AT_RISK_SCHEMA, "func": flag_at_risk},
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
    "update_workshop_performance": {"store": "workshops"},
}
_FACTORIES = {"orders": OrderStore, "workshops": WorkshopStore}

# tools that accept a `queues` override: with a desk they read its live
# chat-side queues (commits move later answers); without one they fall back
# to the 2026-04-01 snapshot inside the tool
_QUEUES_TOOLS = {"get_queue", "estimate_delivery", "rank_candidates",
                 "probe_overload", "earliest_feasible"}

# tools that read the learned-performance store (desk injects its own, so UI
# and bot learn from the same observations)
_PERF_TOOLS = {"estimate_delivery", "update_workshop_performance"}


def tool_schemas():
    """The schemas to pass as `tools=` to the chat completion."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]


def dispatch_tool(name, arguments, *, desk=None):
    """Execute one tool call from the model. Returns the tool's result dict
    (or an error dict the model can read and relay). With a desk, tools read
    its shared stores and live queues. All registered tools are read-only;
    commit_allocation is a backend compatibility function, never an agent tool."""
    entry = TOOL_REGISTRY.get(name)
    if name == "commit_allocation":
        return {"error": "Allocations require the human confirmation endpoint; this tool is read-only."}
    if entry is None:
        return {"error": f"unknown tool {name!r}"}
    kwargs = dict(arguments or {})
    for param, kind in _STORE_KWARGS.get(name, {}).items():
        kwargs[param] = getattr(desk, kind) if desk is not None else _FACTORIES[kind]()
    if desk is not None and name in _QUEUES_TOOLS:
        kwargs["queues"] = desk.state.queues
    if name in _PERF_TOOLS:
        kwargs["perf"] = getattr(desk, "performance", None) or PerformanceStore()
    if name == "flag_at_risk":
        kwargs["desk"] = desk
    context = getattr(desk, "_ranking_context", None)
    if name == "rank_candidates" and context and kwargs.get("order_id") == context["order_id"]:
        excluded = kwargs.get("excluded") or []
        if not isinstance(excluded, list):
            return {"error": "excluded must be a list"}
        kwargs["excluded"] = [x for x in excluded if desk.workshops.resolve(x) not in context["removed"]]
        kwargs["excluded"] += context["required"]
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
