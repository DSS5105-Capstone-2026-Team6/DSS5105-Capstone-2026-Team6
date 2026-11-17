"""api/state.py — per-cookie sessions and the serialisation helpers every
route shares. One session per cookie: sandbox-local desk by default,
optional shared-DB mode per session (the Records toggle)."""

import secrets
import threading
from pathlib import Path

from desk.config import PROVIDERS
from desk.desk import DispatchDesk

RESULTS_DIR = Path(__file__).parent.parent / "results" / "api_sessions"

sessions = {}


def new_desk(shared):
    if shared:
        return DispatchDesk()
    store = RESULTS_DIR / secrets.token_hex(6)
    store.mkdir(parents=True, exist_ok=True)
    return DispatchDesk(storage_dir=str(store))


def get_session(request):
    sid = request.cookies.get("sid") or request.state.new_sid
    if sid not in sessions:
        store = RESULTS_DIR / secrets.token_hex(6)
        store.mkdir(parents=True, exist_ok=True)
        sessions[sid] = {
            "desk": DispatchDesk(storage_dir=str(store)),
            "storage_dir": str(store),
            "shared": False,
            "decisions": {},
            "objective": "hybrid",
            "chat_log": [],
            "provider": "deepseek",
            "model": None,
            "lock": threading.Lock(),   # agent history is not thread-safe;
                                        # parse+dispatch must not interleave
            "timings": [],              # [{kind, ms}] per desk interaction
            "api_errors": 0,
            "shock_target": None,
            "stages": False,
            "item_chats": {},   # decision_id -> [{who, text}] per-card chat
            "tool_history": [],  # archived tool logs of committed/dismissed cards
            "metrics": {"dispatched": 0, "committed": set(), "failed": 0},
            "req_counter": 0,    # Request #N numbering for chat log + cards
        }
    s = sessions[sid]
    s.setdefault("tool_history", [])
    s.setdefault("metrics", {"dispatched": 0, "committed": set(), "failed": 0})
    if "_warmed" not in s:
        s["_warmed"] = True
        warm_caches_async(s)
    return s, sid


def public(d, skipped=False, committed_orders=()):
    p = d.parsed
    committed = bool(p.order_id and p.order_id in committed_orders)
    return {
        "decision_id": d.decision_id,
        "order_id": p.order_id,
        "behaviour": d.behaviour.value,
        "explanation": d.explanation,
        "warnings": list(d.warnings),
        "objective": d.objective,
        "skipped": skipped,
        "already_committed": committed,
        "candidates": [
            {"workshop_id": c.workshop_id, "name": c.name,
             "estimated_finish": c.estimated_finish, "cost": c.cost,
             "defect_risk": c.defect_risk,
             "work_days": float(c.components.get("work_days_expected", 0.0))}
            for c in d.candidates
        ],
        "chosen": d.chosen.workshop_id if d.chosen else None,
        "pieces": p.pieces,
        "due_date": p.due_date,
        "splits": d.splits or [],
        "recommended_split": d.recommended_split,
        "options": list(d.options),
        "tool_log": [{"tool": t.get("tool"), "arguments": t.get("arguments")}
                     for t in d.tool_log],
        "chat": [],
    }


SNAP_TTL = 5.0   # seconds a cached ledger snapshot may serve without even
                 # the version query — every RTT is ~0.6s cross-border, so a
                 # click burst used to cost several Postgres round-trips


def ledger_snapshot(s):
    """(records, queues) from ONE ledger read, cached per desk.

    queues is derived locally from the same read (audit._queues math), so
    state_payload no longer pays a second full table scan for
    desk.state.queues. Within SNAP_TTL the cache serves with zero queries;
    past it, one cheap version query decides whether a full re-read is
    needed. Writes from this session invalidate immediately (see
    invalidate_ledger)."""
    import time as _t
    desk = s["desk"]
    now = _t.monotonic()
    cache = s.get("_ledger_cache")
    if cache is not None and cache[0] is desk:
        _, version, records, queues, ts = cache
        if now - ts < SNAP_TTL:
            return records, queues
        if getattr(desk.audit, "version", None) is not None \
                and desk.audit.version == version:
            s["_ledger_cache"] = (desk, version, records, queues, now)
            return records, queues
    records = desk.audit.load_all()
    queues = dict(desk.audit.initial_queues)
    for rec in records:
        queues[rec.workshop_id] = (queues.get(rec.workshop_id, rec.queue_before)
                                   + rec.queue_after - rec.queue_before)
    version = getattr(desk.audit, "version", None)
    s["_ledger_cache"] = (desk, version, records, queues, now)
    return records, queues


def invalidate_ledger(s):
    """Drop the snapshot after a write from THIS session (commit, split,
    reset, batch) — the TTL path must never serve pre-write state."""
    s.pop("_ledger_cache", None)
    s.pop("_perf_cache", None)


def ledger_records(s):
    return ledger_snapshot(s)[0]


def committed_orders(s):
    return {r.order_id for r in ledger_records(s)}


def warm_caches_async(s):
    """Pre-fill the ledger snapshot and learned-performance caches in the
    background right after a desk is (re)created — the first user action
    then reads warm caches instead of paying cross-border RTTs."""
    desk = s["desk"]
    def run():
        try:
            ledger_snapshot(s)
            first = next(iter(desk.workshops.workshops.items()), None)
            if first:
                perf_learned(s, first[0], profile=first[1])
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


class PerfFacade:
    """Allocator calls perf.learned(wid, profile=...) per workshop — over
    the shared database that is one cross-border RTT per shop per call.
    Route those reads through the session's bulk-filled cache instead."""

    def __init__(self, s):
        self._s = s

    def learned(self, wid, profile=None):
        return perf_learned(self._s, wid, profile)


def perf_learned(s, wid, profile):
    """performance.learned memoized per (desk, 5s). On a miss, all workshops
    are read over ONE pooled connection (learned(_db=...)), so the capacity
    chart costs one round-trip instead of eight."""
    import time as _t
    desk = s["desk"]
    now = _t.monotonic()
    cache = s.get("_perf_cache")
    if cache is not None and cache[0] is desk and now - cache[1] < SNAP_TTL:
        return cache[2].get(wid)
    with desk.performance.database.connect() as db:
        all_learned = {w: desk.performance.learned(w, profile=p, _db=db)
                       for w, p in desk.workshops.workshops.items()}
    # warm the store's own 3s cache too, so allocator paths (lens, scenario,
    # dispatch ranking) that call learned() directly stop paying per-shop RTTs
    wall = _t.time()
    for w, learned in all_learned.items():
        desk.performance._cache[w] = (learned, wall)
    s["_perf_cache"] = (desk, now, all_learned)
    return all_learned.get(wid)


def current_as_of():
    from desk.config import CHAT_AS_OF
    return CHAT_AS_OF


def log(s, speaker, text, reply, decision_id=None):
    """Chat entries carry their decision id so the UI can locate the card
    directly — no order-id guessing (ask cards often have none)."""
    s["chat_log"].append({"speaker": speaker, "text": text, "reply": reply,
                          "decision_id": decision_id})


def archive_tool_log(s, d):
    """Keep a card's tool log reachable after it leaves the open list
    (commit / split / dismiss) — the overlay reads this history."""
    s["tool_history"].append({
        "order_id": d.parsed.order_id,
        "behaviour": d.behaviour.value,
        "tool_log": [{"tool": t.get("tool"), "arguments": t.get("arguments")}
                     for t in d.tool_log],
    })


def state_payload(s, sid):
    desk = s["desk"]
    from desk.tools import flag_at_risk
    records, queues = ledger_snapshot(s)
    committed = {r.order_id for r in records}
    decisions = []
    for x in s["decisions"].values():
        pub = public(x["decision"], x["skipped"], committed)
        pub["chat"] = s["item_chats"].get(x["decision"].decision_id, [])
        pub["msg"] = x["msg"]
        pub["sender"] = x.get("sender")
        pub["req_n"] = x.get("n")
        decisions.append(pub)
    return {
        "sid": sid,
        "shared": s["shared"],
        "objective": s["objective"],
        "queues": queues,
        "workshops": {wid: w.name for wid, w in desk.workshops.workshops.items()},
        "decisions": decisions,
        "chat_log": s["chat_log"],
        "at_risk": flag_at_risk(desk=desk, records=records),
        "as_of": current_as_of(),
        "providers": {k: {"label": v["label"],
                          "models": v["models"]} for k, v in PROVIDERS.items()},
        "provider": s["provider"],
        "model": s["model"],
        "api_errors": s["api_errors"],
        "tool_history": s["tool_history"],
        "shock_target": s["shock_target"],
        "shock_seed": s.get("shock_seed", 5105),
        "stages": s["stages"],
    }


def refresh_stale(s):
    """One-click confirm: re-rank open proposals whose version went stale.
    refresh() returns a NEW decision with a NEW id — the id must stay stable,
    otherwise follow-ups and commits can't find the card ("already closed"
    on a perfectly open request)."""
    desk = s["desk"]
    version = desk.audit.version
    for key in list(s["decisions"].keys()):
        x = s["decisions"][key]
        d = x["decision"]
        if (x["skipped"] or not d.candidates or d.parsed.order_id is None
                or d.state_version in (None, version)):
            continue
        fresh = desk.refresh(d)
        fresh.decision_id = key
        x["decision"] = fresh


def refresh_stale_async(s):
    """Re-rank stale proposals in the background so recommendations (the
    star) catch up after a commit without blocking the commit response."""
    def run():
        try:
            with s["lock"]:
                refresh_stale(s)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()
