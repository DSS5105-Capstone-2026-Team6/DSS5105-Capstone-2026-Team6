"""api/routes/dashboard.py — state, records, analytics, chart data, reset."""

from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from desk.config import PROVIDERS
from api import charts
from api.state import (committed_orders, get_session, public, state_payload)

router = APIRouter()


@router.get("/api/state")
def state(request: Request):
    s, sid = get_session(request)
    return state_payload(s, sid)


@router.get("/api/orders")
def open_orders(request: Request):
    s, _ = get_session(request)
    return [o["order_id"] for o in s["desk"].orders.orders
            if o.get("status") != "COMPLETE"]


@router.get("/api/records")
def records(request: Request):
    s, _ = get_session(request)
    return [asdict(r) for r in s["desk"].audit.load_all()]


def _behaviour_dist(s):
    dist = {}
    for x in s["decisions"].values():
        b = x["decision"].behaviour.value
        dist[b] = dist.get(b, 0) + 1
    return dist


def _usage_rows(s):
    from collections import Counter
    from datetime import datetime, timezone
    usage = Counter()
    try:
        with s["desk"].agent.budget.database.connect() as db:
            for _, at in db.execute("SELECT scope, at FROM api_usage"):
                usage[datetime.fromtimestamp(at, timezone.utc).date().isoformat()] += 1
    except Exception:
        pass
    return usage


def _timeline_points(desk):
    pts = []
    seen = set()
    for r in desk.audit.load_all():
        w = desk.workshops.workshops[r.workshop_id]
        if r.workshop_id not in seen:
            seen.add(r.workshop_id)
            pts.append({"t": "2026-04-01", "queue": w.queue0, "workshop": w.name})
        pts.append({"t": r.committed_at, "queue": r.queue_after, "workshop": w.name})
    return pts


@router.get("/api/chart_data/{kind}")
def chart_data(kind: str, request: Request):
    """JSON for the Plotly dashboard (box-zoom rescales both axes — no
    server round-trip, so no PNGs)."""
    s, _ = get_session(request)
    desk = s["desk"]
    if kind == "timeline":
        data = charts.timeline(_timeline_points(desk))
    elif kind == "capacity":
        rows = [{"workshop": w.name,
                 "profile": w.capacity,
                 "current": (l["eff_capacity"] if (l := desk.performance.learned(wid, profile=w)) else w.capacity)}
                for wid, w in sorted(desk.workshops.workshops.items())]
        data = charts.capacity(rows)
    elif kind == "lens":
        from desk.allocator import rank_candidates
        from desk.config import chat_today
        from datetime import date
        open_order_ids = [o["order_id"] for o in desk.orders.orders
                          if o.get("status") != "COMPLETE"]
        if not open_order_ids:
            return JSONResponse({"error": "no open orders"}, status_code=404)
        order_id = request.query_params.get("order_id") or open_order_ids[0]
        res = rank_candidates(order_id, objective=s["objective"],
                              orders=desk.orders, store=desk.workshops,
                              queues=desk.state.queues, perf=desk.performance)
        due = date.fromisoformat(desk.orders.by_id(order_id)["due_date"])
        data = charts.lens(res.get("candidates", []), res.get("chosen"),
                           (due - chat_today()).days)
    elif kind == "dist":
        data = charts.distribution(_behaviour_dist(s))
    elif kind == "errors":
        dist = _behaviour_dist(s)
        errors = {b: dist.get(b, 0) for b in ("refuse", "impossible", "no_data", "ask")}
        errors["api_error"] = s["api_errors"]
        data = charts.error_types(errors)
    elif kind == "usage":
        usage = _usage_rows(s)
        data = charts.usage_trend([{"day": d, "rounds": n}
                                   for d, n in sorted(usage.items())])
    elif kind == "map":
        data = charts.objective_map([
            {"workshop": w.name, "cost": w.cost, "defect": w.defect_rate,
             "queue": desk.state.queues[wid]}
            for wid, w in desk.workshops.workshops.items()])
    else:
        return JSONResponse({"error": "unknown chart"}, status_code=404)
    return data


@router.get("/api/analytics")
def analytics(request: Request):
    """Multi-dimensional dashboard metrics: distribution, rates, latency,
    throughput, error types, model usage, and queue backlog."""
    s, _ = get_session(request)
    desk = s["desk"]
    decisions = [public(x["decision"], x["skipped"], committed_orders(s))
                 for x in s["decisions"].values()]
    dist = {}
    for d in decisions:
        dist[d["behaviour"]] = dist.get(d["behaviour"], 0) + 1
    records = desk.audit.load_all()
    committed_ids = {r.order_id for r in records}
    # per-session rates: a split commit writes one ledger row per part but is
    # still ONE answered request, so count unique order ids against the
    # number of requests dispatched — never ledger rows vs open cards
    m = s["metrics"]
    done = len(m["committed"])
    failed = m["failed"]
    total = max(1, m["dispatched"])
    timings = s["timings"]
    avg_ms = round(sum(t["ms"] for t in timings) / len(timings), 1) if timings else 0
    queues = desk.state.queues
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    usage = _usage_rows(s)
    errors = {b: dist.get(b, 0) for b in ("refuse", "impossible", "no_data", "ask")}
    errors["api_error"] = s["api_errors"]
    return {
        "tiles": {
            "requests": len(decisions),
            "committed": len(committed_ids),
            "pending": sum(1 for d in decisions
                           if not d["skipped"] and not d["already_committed"]),
            "success_rate": round(100 * done / total, 1),
            "failure_rate": round(100 * failed / total, 1),
            "avg_ms": avg_ms,
            "interactions": len(timings),
            "llm_rounds_today": usage.get(today, 0),
            "backlog_days": round(sum(queues.values()), 1),
            "provider": s["provider"],
            "model": s["model"] or PROVIDERS[s["provider"]]["models"][0][0],
        },
        "dist": dist,
        "errors": errors,
        "usage": [{"day": d, "rounds": n} for d, n in sorted(usage.items())],
        "commits": len(records),
    }


class BatchBody(BaseModel):
    workshop_id: str
    pieces: int
    promised: str
    actual: str


@router.post("/api/batch")
def record_batch(body: BatchBody, request: Request):
    s, sid = get_session(request)
    desk = s["desk"]
    from desk.tools import update_workshop_performance
    out = update_workshop_performance(
        body.workshop_id, body.pieces, body.promised, body.actual,
        store=desk.workshops, perf=desk.performance)
    if "error" in out:
        return {"error": out["error"]}
    st = state_payload(s, sid)
    st["batch_note"] = out["note"]
    return st


@router.post("/api/reset")
def reset(request: Request):
    s, sid = get_session(request)
    s["desk"].audit.reset()
    s["desk"].performance.clear()
    s["decisions"] = {}
    s["chat_log"] = []
    s["metrics"] = {"dispatched": 0, "committed": set(), "failed": 0}
    return state_payload(s, sid)
