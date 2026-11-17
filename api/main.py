"""
api/main.py — full FastAPI front-end for the DispatchDesk (Streamlit parity).

One session per cookie: sandbox-local desk by default, optional shared-DB
mode per session (the Records toggle). desk/ is used as-is.

Run:  uvicorn api.main:app --port 8000
"""

import os
import secrets
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from desk.budget import BudgetExceeded
from desk.chat_dump import split_chat_dump
from desk.config import AS_OF_OPTIONS, PROVIDERS
from desk.desk import DispatchDesk, ProposalChanged

STATIC_DIR = Path(__file__).parent / "static"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
RESULTS_DIR = Path(__file__).parent.parent / "results" / "api_sessions"

app = FastAPI(title="Dispatch Desk API")
_sessions = {}
_AUTH_TOKENS = {}


@app.middleware("http")
async def ensure_session_cookie(request: Request, call_next):
    """Sessions were created per request because the sid was never written
    back to the client — every API call started a fresh session (decisions,
    objective, chat log all reset). Issue and persist a sid cookie."""
    request.state.new_sid = None
    if "sid" not in request.cookies:
        request.state.new_sid = secrets.token_hex(12)
    response = await call_next(request)
    if request.state.new_sid:
        response.set_cookie("sid", request.state.new_sid,
                            max_age=7 * 86400, samesite="lax")
    return response


# ---------------- helpers ----------------

def _new_desk(shared):
    if shared:
        return DispatchDesk()
    store = RESULTS_DIR / secrets.token_hex(6)
    store.mkdir(parents=True, exist_ok=True)
    return DispatchDesk(storage_dir=str(store))


def _session(request: Request):
    sid = request.cookies.get("sid") or request.state.new_sid
    if sid not in _sessions:
        store = RESULTS_DIR / secrets.token_hex(6)
        store.mkdir(parents=True, exist_ok=True)
        _sessions[sid] = {
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
        }
    s = _sessions[sid]
    s.setdefault("tool_history", [])
    s.setdefault("metrics", {"dispatched": 0, "committed": set(), "failed": 0})
    return s, sid


def _archive_tool_log(s, d):
    """Keep a card's tool log reachable after it leaves the open list
    (commit / split / dismiss) — the overlay reads this history."""
    s["tool_history"].append({
        "order_id": d.parsed.order_id,
        "behaviour": d.behaviour.value,
        "tool_log": [{"tool": t.get("tool"), "arguments": t.get("arguments")}
                     for t in d.tool_log],
    })


def _public(d, skipped=False, committed_orders=()):
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
        "splits": d.splits or [],
        "recommended_split": d.recommended_split,
        "options": list(d.options),
        "tool_log": [{"tool": t.get("tool"), "arguments": t.get("arguments")}
                     for t in d.tool_log],
        "chat": [],
    }


def _committed_orders(s):
    return {r.order_id for r in s["desk"].audit.load_all()}


def _state(s, sid):
    desk = s["desk"]
    from desk.tools import flag_at_risk
    committed = _committed_orders(s)
    decisions = []
    for x in s["decisions"].values():
        pub = _public(x["decision"], x["skipped"], committed)
        pub["chat"] = s["item_chats"].get(x["decision"].decision_id, [])
        pub["msg"] = x["msg"]
        decisions.append(pub)
    return {
        "sid": sid,
        "shared": s["shared"],
        "objective": s["objective"],
        "queues": dict(desk.state.queues),
        "workshops": {wid: w.name for wid, w in desk.workshops.workshops.items()},
        "decisions": decisions,
        "chat_log": s["chat_log"],
        "at_risk": flag_at_risk(desk=desk),
        "as_of": _current_as_of(),
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


def _log(s, speaker, text, reply, decision_id=None):
    """Chat entries carry their decision id so the UI can locate the card
    directly — no order-id guessing (ask cards often have none)."""
    s["chat_log"].append({"speaker": speaker, "text": text, "reply": reply,
                          "decision_id": decision_id})


def _current_as_of():
    from desk.config import CHAT_AS_OF
    return CHAT_AS_OF


def _refresh_stale_async(s):
    """Re-rank stale proposals in the background so recommendations (the
    star) catch up after a commit without blocking the commit response."""
    def run():
        try:
            with s["lock"]:
                _refresh_stale(s)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def _refresh_stale(s):
    """One-click confirm: re-rank open proposals whose version went stale.
    refresh() returns a NEW decision with a NEW id — the dict key must move
    too, otherwise follow-ups and commits can't find the card ("already
    closed" on a perfectly open request)."""
    desk = s["desk"]
    version = desk.audit.version
    for key in list(s["decisions"].keys()):
        x = s["decisions"][key]
        d = x["decision"]
        if (x["skipped"] or not d.candidates or d.parsed.order_id is None
                or d.state_version in (None, version)):
            continue
        fresh = desk.refresh(d)
        # refresh mints a new id, but the proposal's id must stay stable —
        # cards in the DOM and follow-up requests all reference it
        fresh.decision_id = key
        x["decision"] = fresh


# ---------------- pages & auth ----------------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody):
    if not APP_PASSWORD or body.password == APP_PASSWORD:
        token = secrets.token_hex(16)
        _AUTH_TOKENS[token] = time.time() + 30 * 86400
        return JSONResponse({"token": token})
    return JSONResponse({"error": "Wrong password."}, status_code=401)


def _authed(request):
    if not APP_PASSWORD:
        return True
    token = request.cookies.get("auth") or request.headers.get("x-auth")
    return token in _AUTH_TOKENS and _AUTH_TOKENS[token] > time.time()


# ---------------- intake ----------------

@app.get("/api/samples")
def samples():
    from desk.config import DATA_DIR
    return sorted(p.name for p in DATA_DIR.glob("dispatch*.txt"))


@app.get("/api/sample")
def sample(name: str):
    from desk.config import DATA_DIR
    p = DATA_DIR / name
    if p.parent != DATA_DIR or not p.exists():
        return {"error": "unknown sample"}
    return {"name": name, "text": p.read_text(encoding="utf-8")}


class ParseBody(BaseModel):
    text: str


class SplitBody(BaseModel):
    text: str


@app.post("/api/split")
def split(body: SplitBody):
    """Split an inbox dump into individual messages (for per-line progress)."""
    return {"lines": split_chat_dump(body.text.strip())}


@app.post("/api/parse")
def parse(body: ParseBody, request: Request):
    s, _ = _session(request)
    from desk.llm_parser import parse_message
    t0 = time.perf_counter()
    with s["lock"]:
        try:
            out = parse_message(body.text, s["desk"].agent)
        except Exception as exc:
            s["api_errors"] += 1
            return {"error": f"Parse failed: {exc}"}
        # attach the register row per parsed order so the UI can render the
        # same field-by-field comparison card as the Streamlit parser view
        for o in out.get("orders") or []:
            rec = s["desk"].orders.by_id(o.get("order_id")) if o.get("order_id") else None
            o["register"] = dict(rec) if rec else None
    s["timings"].append({"kind": "parse", "ms": round((time.perf_counter() - t0) * 1000)})
    return out


class DispatchBody(BaseModel):
    text: str
    new_session: bool = False


@app.post("/api/dispatch")
def dispatch(body: DispatchBody, request: Request):
    s, sid = _session(request)
    if body.new_session:
        s["decisions"] = {}
        s["tool_history"] = []
        s["metrics"] = {"dispatched": 0, "committed": set(), "failed": 0}
    desk = s["desk"]
    from desk.contracts import Behaviour, Decision
    out = []
    for msg in split_chat_dump(body.text.strip()):
        t0 = time.perf_counter()
        with s["lock"]:
            try:
                d = desk.handle_message(msg, requester="web")
            except BudgetExceeded:
                s["api_errors"] += 1
                d = Decision(request_id="", behaviour=Behaviour.ASK,
                             explanation="Request limit reached. Please try again later.")
            except Exception:
                s["api_errors"] += 1
                d = Decision(request_id="", behaviour=Behaviour.ASK,
                             explanation="Request failed. Please retry later.")
            s["decisions"][d.decision_id] = {"decision": d, "msg": msg, "skipped": False}
            s["metrics"]["dispatched"] += 1
            if d.behaviour in (Behaviour.REFUSE, Behaviour.NO_DATA):
                s["metrics"]["failed"] += 1
            out.append(d)
            _log(s, "dispatcher", msg, d.explanation, decision_id=d.decision_id)
        s["timings"].append({"kind": "dispatch", "ms": round((time.perf_counter() - t0) * 1000)})
    _refresh_stale(s)
    return _state(s, sid)


# ---------------- follow-up / confirm ----------------

class FollowupBody(BaseModel):
    decision_id: str
    text: str


@app.post("/api/followup")
def followup(body: FollowupBody, request: Request):
    s, sid = _session(request)
    desk = s["desk"]
    item = s["decisions"].get(body.decision_id)
    if item is None:
        st = _state(s, sid)
        st["reply"] = ("This request is already closed (committed or "
                       "dismissed) — there is nothing left to discuss.")
        st["notice"] = st["reply"]
        return st
    t0 = time.perf_counter()
    try:
        with s["lock"]:
            updated, record, reply = desk.follow_up(body.text, item["decision"],
                                                    requester="web")
    except BudgetExceeded:
        return {"error": "Request limit reached. Please try again later."}
    except Exception:
        return {"error": "Request failed. Please retry later."}
    finally:
        s["timings"].append({"kind": "followup",
                             "ms": round((time.perf_counter() - t0) * 1000)})
    thread = s["item_chats"].setdefault(body.decision_id, [])
    thread.append({"who": "you", "text": body.text})
    # every path that returns a reply must record it — the question/cancel
    # branches (updated=None, record=None) used to drop the desk's answer
    if reply:
        thread.append({"who": "desk", "text": reply})
    if record is not None:
        del s["decisions"][body.decision_id]
    elif updated is not None:
        # follow_up may return a NEW decision object with a NEW id — keep the
        # proposal's id stable so cards and follow-ups stay addressable
        updated.decision_id = body.decision_id
        item["decision"] = updated
    _log(s, "dispatcher", body.text, reply or "", decision_id=body.decision_id)
    st = _state(s, sid)
    st["reply"] = reply
    return st


def _commit(s, d, wid):
    target = next((c for c in d.candidates if c.workshop_id == wid), None)
    if target is None:
        return None, f"{wid} is not a candidate."
    try:
        return s["desk"].confirm(replace(d, chosen=target), committed_by="web"), None
    except ProposalChanged as exc:
        # one-click semantics: the card went stale after another commit;
        # retry once with the refreshed decision (same as confirm_all)
        fresh = exc.decision
        target = next((c for c in fresh.candidates if c.workshop_id == wid), None)
        if target is None:
            # previously this was a silent "stale" — the user saw nothing and
            # assumed the click did not register. Surface it instead.
            return fresh, (f"{wid} dropped out of the top candidates after "
                           f"the queue changed — the card was refreshed, "
                           f"re-pick a workshop.")
        try:
            return s["desk"].confirm(replace(fresh, chosen=target),
                                     committed_by="web"), None
        except (ProposalChanged, ValueError) as exc2:
            return fresh, str(exc2)
    except ValueError as exc:
        return None, str(exc)


class ConfirmBody(BaseModel):
    decision_id: str
    workshop_id: str


@app.post("/api/confirm")
def confirm(body: ConfirmBody, request: Request):
    s, sid = _session(request)
    item = s["decisions"].get(body.decision_id)
    if item is None:
        return {"error": "Unknown or already committed decision."}
    result, err = _commit(s, item["decision"], body.workshop_id)
    if err == "stale":
        item["decision"] = result
    elif err is not None and result is not None:
        # refreshed but the picked workshop fell out of the top candidates —
        # keep the fresh card on screen and tell the user why nothing happened
        item["decision"] = result
        return {"error": err}
    elif err is None:
        _archive_tool_log(s, item["decision"])
        del s["decisions"][body.decision_id]
        s["metrics"]["committed"].add(result.order_id)
        _log(s, "dispatcher", f"(card) {body.workshop_id}",
             f"Committed {result.record_id} — {result.order_id} → {result.workshop_id}.")
    else:
        return {"error": err}
    _refresh_stale_async(s)   # stars catch up in the background, no freeze
    return _state(s, sid)


class SplitBody(BaseModel):
    decision_id: str
    index: int = 0


@app.post("/api/confirm_split")
def confirm_split(body: SplitBody, request: Request):
    s, sid = _session(request)
    item = s["decisions"].get(body.decision_id)
    if item is None:
        st = _state(s, sid)
        st["reply"] = ("This request is already closed (committed or "
                       "dismissed) — there is nothing left to discuss.")
        st["notice"] = st["reply"]
        return st
    decision = item["decision"]
    try:
        records = s["desk"].confirm_split(decision, body.index,
                                          committed_by="web")
    except ProposalChanged as exc:
        # stale after another commit: retry once with the refreshed proposal
        # (same one-click semantics as _commit)
        item["decision"] = exc.decision
        try:
            records = s["desk"].confirm_split(exc.decision, body.index,
                                              committed_by="web")
        except (ProposalChanged, ValueError) as exc2:
            return {"error": str(exc2)}
    except ValueError as exc:
        return {"error": str(exc)}
    _archive_tool_log(s, decision)
    del s["decisions"][body.decision_id]
    s["metrics"]["committed"].add(records[0].order_id)   # split = one request
    _log(s, "dispatcher", f"(split #{body.index + 1})",
         f"Committed {len(records)} parts.")
    _refresh_stale_async(s)
    return _state(s, sid)


@app.post("/api/confirm_all")
def confirm_all(request: Request):
    s, sid = _session(request)
    from desk.contracts import Behaviour
    # only ALLOCATE cards are batch-confirmable — a refusal with candidates
    # is still a refusal (the Streamlit desk filters the same way)
    open_d = [x["decision"] for x in s["decisions"].values()
              if not x["skipped"]
              and x["decision"].behaviour is Behaviour.ALLOCATE
              and x["decision"].candidates
              and x["decision"].chosen]
    results, failures = s["desk"].confirm_all(open_d, committed_by="web")
    for d, record in results:
        _archive_tool_log(s, d)
        s["decisions"].pop(d.decision_id, None)
        s["metrics"]["committed"].add(record.order_id)
        _log(s, "dispatcher", f"(confirm all) {d.parsed.order_id}",
             f"Committed {record.record_id}.")
    st = _state(s, sid)
    st["failures"] = failures
    return st


class IdBody(BaseModel):
    decision_id: str


@app.post("/api/skip")
def skip(body: IdBody, request: Request):
    s, sid = _session(request)
    item = s["decisions"].get(body.decision_id)
    if item:
        item["skipped"] = True
        _log(s, "dispatcher", "(skip)", f"Skipped {item['decision'].parsed.order_id}.")
    return _state(s, sid)


@app.post("/api/dismiss")
def dismiss(body: IdBody, request: Request):
    s, sid = _session(request)
    item = s["decisions"].pop(body.decision_id, None)
    if item:
        _archive_tool_log(s, item["decision"])
    return _state(s, sid)


class RerankBody(BaseModel):
    decision_id: str | None = None
    objective: str


@app.post("/api/rerank")
def rerank(body: RerankBody, request: Request):
    s, sid = _session(request)
    s["objective"] = body.objective
    desk = s["desk"]
    targets = ([body.decision_id] if body.decision_id
               else list(s["decisions"].keys()))
    for did in targets:
        item = s["decisions"].get(did)
        if item and item["decision"].candidates:
            fresh = desk.refresh(
                replace(item["decision"], objective=body.objective))
            fresh.decision_id = did   # keep the proposal's id stable
            item["decision"] = fresh
    return _state(s, sid)


# ---------------- world / shock ----------------

class WorldBody(BaseModel):
    as_of: str
    stages: bool


@app.post("/api/world")
def world(body: WorldBody, request: Request):
    from desk.config import set_as_of
    s, sid = _session(request)
    set_as_of(body.as_of)
    s["stages"] = body.stages
    s["shock_target"] = None      # a world change clears any active shock
    if s["shared"]:
        s["desk"] = DispatchDesk(stages=body.stages)
    else:
        s["desk"] = DispatchDesk(stages=body.stages, storage_dir=s["storage_dir"])
    return _state(s, sid)


class ShockBody(BaseModel):
    seed: int = 5105


@app.post("/api/shock")
def shock_on(body: ShockBody, request: Request):
    import random
    s, sid = _session(request)
    desk = s["desk"]
    active = [w for w in desk.workshops.workshops.values() if w.status == "ACTIVE"]
    target = random.Random(body.seed).choice(sorted(active, key=lambda w: w.workshop_id))
    target.status = "SUSPENDED"
    s["shock_target"] = target.workshop_id
    s["shock_seed"] = body.seed
    return _state(s, sid)


@app.delete("/api/shock")
def shock_off(request: Request):
    s, sid = _session(request)
    desk = s["desk"]
    # restore the tracked target first (the Streamlit desk does the same),
    # then any other SUSPENDED workshop
    if s["shock_target"] in desk.workshops.workshops:
        desk.workshops.workshops[s["shock_target"]].status = "ACTIVE"
    for w in desk.workshops.workshops.values():
        if w.status == "SUSPENDED":
            w.status = "ACTIVE"
    s["shock_target"] = None
    return _state(s, sid)


# ---------------- scenario ----------------

class ScenarioBody(BaseModel):
    order_id: str
    preview_date: str | None = None
    closed: bool = False
    delay: int = 0
    noise_pct: float = 0
    seed: int = 5105
    objective: str = "hybrid"


@app.post("/api/scenario")
def scenario(body: ScenarioBody, request: Request):
    from datetime import date
    from app.tabs.desk.scenario import compare_sunday
    s, _ = _session(request)
    desk = s["desk"]
    pd_ = date.fromisoformat(body.preview_date) if body.preview_date else None
    result = compare_sunday(body.order_id, desk.orders, desk.workshops,
                            dict(desk.state.queues), body.closed, body.delay,
                            perf=desk.performance, noise_pct=body.noise_pct,
                            seed=body.seed, preview_date=pd_)
    if "error" in result:
        return result
    from desk.allocator import order_rows
    result["baseline_pick"] = order_rows(result["baseline"], body.objective)[0]
    result["scenario_pick"] = order_rows(result["scenario"], body.objective)[0]
    return result


# ---------------- records / dashboard / reset ----------------

@app.get("/api/state")
def state(request: Request):
    s, sid = _session(request)
    return _state(s, sid)


@app.get("/api/orders")
def open_orders(request: Request):
    s, _ = _session(request)
    return [o["order_id"] for o in s["desk"].orders.orders
            if o.get("status") != "COMPLETE"]


@app.get("/api/records")
def records(request: Request):
    s, _ = _session(request)
    return [asdict(r) for r in s["desk"].audit.load_all()]


@app.get("/api/chart/{kind}")
def chart(kind: str, request: Request):
    from fastapi.responses import Response
    from api import charts
    s, _ = _session(request)
    desk = s["desk"]
    if kind == "timeline":
        pts = []
        seen = set()
        for r in desk.audit.load_all():
            w = desk.workshops.workshops[r.workshop_id]
            if r.workshop_id not in seen:
                seen.add(r.workshop_id)
                pts.append({"t": "2026-04-01", "queue": w.queue0, "workshop": w.name})
            pts.append({"t": r.committed_at, "queue": r.queue_after, "workshop": w.name})
        png = charts.timeline(pts)
    elif kind == "capacity":
        rows = [{"workshop": w.name,
                 "profile": w.capacity,
                 "current": (l["eff_capacity"] if (l := desk.performance.learned(wid, profile=w)) else w.capacity)}
                for wid, w in sorted(desk.workshops.workshops.items())]
        png = charts.capacity(rows)
    elif kind == "lens":
        from desk.allocator import rank_candidates
        from desk.config import chat_today
        from datetime import date
        open_orders = [o["order_id"] for o in desk.orders.orders
                       if o.get("status") != "COMPLETE"]
        order_id = request.query_params.get("order_id") or open_orders[0]
        res = rank_candidates(order_id, objective=s["objective"],
                              orders=desk.orders, store=desk.workshops,
                              queues=desk.state.queues, perf=desk.performance)
        due = date.fromisoformat(desk.orders.by_id(order_id)["due_date"])
        png = charts.lens(res.get("candidates", []), res.get("chosen"),
                          (due - chat_today()).days)
    elif kind == "dist":
        dec = [_public(x["decision"], x["skipped"], ()) for x in s["decisions"].values()]
        dist = {}
        for d in dec:
            dist[d["behaviour"]] = dist.get(d["behaviour"], 0) + 1
        png = charts.distribution(dist)
    elif kind == "errors":
        dec = [_public(x["decision"], x["skipped"], ()) for x in s["decisions"].values()]
        dist = {}
        for d in dec:
            dist[d["behaviour"]] = dist.get(d["behaviour"], 0) + 1
        errors = {b: dist.get(b, 0) for b in ("refuse", "impossible", "no_data", "ask")}
        errors["api_error"] = s["api_errors"]
        png = charts.error_types(errors)
    elif kind == "usage":
        from collections import Counter
        from datetime import datetime, timezone
        usage = Counter()
        try:
            with s["desk"].agent.budget.database.connect() as db:
                for _, at in db.execute("SELECT scope, at FROM api_usage"):
                    usage[datetime.fromtimestamp(at, timezone.utc).date().isoformat()] += 1
        except Exception:
            pass
        png = charts.usage_trend([{"day": d, "rounds": n}
                                  for d, n in sorted(usage.items())])
    elif kind == "map":
        png = charts.objective_map([
            {"workshop": w.name, "cost": w.cost, "defect": w.defect_rate,
             "queue": desk.state.queues[wid]}
            for wid, w in desk.workshops.workshops.items()])
    else:
        return JSONResponse({"error": "unknown chart"}, status_code=404)
    return Response(content=png, media_type="image/png")


@app.get("/api/analytics")
def analytics(request: Request):
    """Multi-dimensional dashboard metrics: distribution, rates, latency,
    throughput, error types, model usage, and queue backlog."""
    s, _ = _session(request)
    desk = s["desk"]
    decisions = [_public(x["decision"], x["skipped"], _committed_orders(s))
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
    from collections import Counter
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    usage = Counter()
    try:
        with desk.agent.budget.database.connect() as db:
            for scope, at in db.execute("SELECT scope, at FROM api_usage"):
                day = datetime.fromtimestamp(at, timezone.utc).date().isoformat()
                usage[day] += 1
    except Exception:
        pass
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


@app.post("/api/batch")
def record_batch(body: BatchBody, request: Request):
    s, sid = _session(request)
    desk = s["desk"]
    from desk.tools import update_workshop_performance
    out = update_workshop_performance(
        body.workshop_id, body.pieces, body.promised, body.actual,
        store=desk.workshops, perf=desk.performance)
    if "error" in out:
        return {"error": out["error"]}
    st = _state(s, sid)
    st["batch_note"] = out["note"]
    return st


@app.get("/api/dashboard")
def dashboard(request: Request):
    s, _ = _session(request)
    desk = s["desk"]
    from desk.allocator import rank_candidates
    records = desk.audit.load_all()
    timeline = []
    seen = set()
    for r in records:
        w = desk.workshops.workshops[r.workshop_id]
        if r.workshop_id not in seen:
            seen.add(r.workshop_id)
            timeline.append({"t": "2026-04-01", "queue": w.queue0,
                             "workshop": w.name})
        timeline.append({"t": r.committed_at, "queue": r.queue_after,
                         "workshop": w.name})
    open_orders = [o["order_id"] for o in desk.orders.orders
                   if o.get("status") != "COMPLETE"]
    lens = None
    if open_orders:
        res = rank_candidates(open_orders[0], objective=s["objective"],
                              orders=desk.orders, store=desk.workshops,
                              queues=desk.state.queues, perf=desk.performance)
        if "error" not in res:
            lens = res
    capacity = []
    from desk.performance import MIN_SAMPLES
    for wid, w in sorted(desk.workshops.workshops.items()):
        learned = desk.performance.learned(wid, profile=w)
        capacity.append({"workshop": w.name,
                         "profile": w.capacity,
                         "current": learned["eff_capacity"] if learned else w.capacity,
                         "source": ("learned" if learned else
                                    f"observing" if desk.performance._samples(wid) else "profile")})
    bubbles = [{"workshop": w.name, "cost": w.cost, "defect": w.defect_rate,
                "queue": round(desk.state.queues[wid], 2)}
               for wid, w in desk.workshops.workshops.items()]
    return {"timeline": timeline, "lens": lens, "capacity": capacity,
            "bubbles": bubbles, "lens_order": open_orders[0] if open_orders else None}


@app.post("/api/reset")
def reset(request: Request):
    s, sid = _session(request)
    s["desk"].audit.reset()
    s["desk"].performance.clear()
    s["decisions"] = {}
    s["chat_log"] = []
    return _state(s, sid)


class ProviderBody(BaseModel):
    provider: str
    model: str | None = None


@app.post("/api/provider")
def provider(body: ProviderBody, request: Request):
    s, sid = _session(request)
    if body.provider not in PROVIDERS:
        return {"error": f"unknown provider {body.provider}"}
    try:
        new_desk = (DispatchDesk(provider=body.provider, model=body.model)
                    if s["shared"]
                    else DispatchDesk(provider=body.provider, model=body.model,
                                      storage_dir=s["storage_dir"]))
    except Exception as exc:
        # keep the old desk; the UI must not lose state on a bad key
        return {"error": f"Cannot switch to {body.provider}: {exc}"}
    s["provider"] = body.provider
    s["model"] = body.model
    s["desk"] = new_desk
    return _state(s, sid)


class CompareBody(BaseModel):
    models: list[str] = []      # ["deepseek:deepseek-chat", "openai:gpt-6-luna"]
    limit: int = 3


@app.post("/api/compare_models")
def compare_models(body: CompareBody, request: Request):
    """Run the first `limit` dev-inbox requests through each model and score
    behaviour labels against data/labels_inbox.json."""
    from desk.config import DATA_DIR
    from desk.chat_dump import ENVELOPE
    import json as _json

    labels_path = DATA_DIR / "labels_inbox.json"
    inbox_path = DATA_DIR / "dispatch_requests.txt"
    raw = _json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else []
    labels = {x["request_id"]: x for x in raw} if isinstance(raw, list) else raw
    lines = [l for l in inbox_path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")][:max(1, body.limit)]

    out = []
    for spec in body.models:
        provider, _, model = spec.partition(":")
        entry = {"model": spec, "provider": provider, "results": [], "error": None}
        try:
            desk = DispatchDesk(provider=provider, model=model or None)
            for line in lines:
                rid = (ENVELOPE.match(line).group(1) if ENVELOPE.match(line) else line[:3])
                try:
                    d = desk.handle_message(line, requester="compare")
                    expected = (labels.get(rid) or {}).get("behaviour")
                    got = d.behaviour.value
                    entry["results"].append({
                        "id": rid, "expected": expected, "got": got,
                        "ok": expected is None or expected == got})
                except Exception as exc:
                    entry["results"].append({"id": rid, "expected": None,
                                             "got": "error", "ok": False,
                                             "error": str(exc)[:120]})
        except Exception as exc:
            entry["error"] = str(exc)[:200]
        if entry["results"]:
            scored = [r for r in entry["results"] if r["expected"]]
            entry["accuracy"] = (round(sum(r["ok"] for r in scored) / len(scored), 3)
                                 if scored else None)
        out.append(entry)
    return {"models": out, "n": len(lines)}


class ShareBody(BaseModel):
    shared: bool


@app.post("/api/share")
def share(body: ShareBody, request: Request):
    s, sid = _session(request)
    s["shared"] = body.shared
    s["decisions"] = {}
    s["desk"] = DispatchDesk() if body.shared else _new_desk(False)
    return _state(s, sid)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
