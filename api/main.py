"""
api/main.py — full FastAPI front-end for the DispatchDesk (Streamlit parity).

One session per cookie: sandbox-local desk by default, optional shared-DB
mode per session (the Records toggle). desk/ is used as-is.

Run:  uvicorn api.main:app --port 8000
"""

import os
import secrets
import sys
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
_sessions = {}   # sid -> {"desk", "decisions": {id: {decision, msg, skipped}},
                  #        "objective", "chat_log": [], "authed": bool}
_AUTH_TOKENS = {}


# ---------------- helpers ----------------

def _new_desk(shared):
    if shared:
        return DispatchDesk()
    store = RESULTS_DIR / secrets.token_hex(6)
    store.mkdir(parents=True, exist_ok=True)
    return DispatchDesk(storage_dir=str(store))


def _session(request: Request):
    sid = request.cookies.get("sid")
    if sid not in _sessions:
        _sessions[sid or secrets.token_hex(12)] = None
        sid = [k for k, v in _sessions.items() if v is None][-1] if sid not in _sessions else sid
        _sessions[sid] = {
            "desk": _new_desk(shared=False),
            "shared": False,
            "decisions": {},
            "objective": "hybrid",
            "chat_log": [],
            "provider": "deepseek",
            "model": None,
        }
    return _sessions[sid], sid


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
    }


def _committed_orders(s):
    return {r.order_id for r in s["desk"].audit.load_all()}


def _state(s, sid):
    desk = s["desk"]
    from desk.tools import flag_at_risk
    committed = _committed_orders(s)
    return {
        "sid": sid,
        "shared": s["shared"],
        "objective": s["objective"],
        "queues": dict(desk.state.queues),
        "workshops": {wid: w.name for wid, w in desk.workshops.workshops.items()},
        "decisions": [_public(x["decision"], x["skipped"], committed)
                      for x in s["decisions"].values()],
        "chat_log": s["chat_log"],
        "at_risk": flag_at_risk(desk=desk),
        "as_of": os.environ.get("CHAT_AS_OF", ""),
        "providers": {k: {"label": v["label"],
                          "models": v["models"]} for k, v in PROVIDERS.items()},
        "provider": s["provider"],
    }


def _log(s, speaker, text, reply):
    s["chat_log"].append({"speaker": speaker, "text": text, "reply": reply})


def _refresh_stale(s):
    """One-click confirm: re-rank open proposals whose version went stale."""
    desk = s["desk"]
    version = desk.audit.version
    for x in s["decisions"].values():
        d = x["decision"]
        if (x["skipped"] or not d.candidates or d.parsed.order_id is None
                or d.state_version in (None, version)):
            continue
        x["decision"] = desk.refresh(d)


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


@app.post("/api/parse")
def parse(body: ParseBody, request: Request):
    s, _ = _session(request)
    from desk.llm_parser import parse_message
    try:
        return parse_message(body.text, s["desk"].agent)
    except Exception as exc:
        return {"error": f"Parse failed: {exc}"}


class DispatchBody(BaseModel):
    text: str
    new_session: bool = False


@app.post("/api/dispatch")
def dispatch(body: DispatchBody, request: Request):
    s, sid = _session(request)
    if body.new_session:
        s["decisions"] = {}
    desk = s["desk"]
    from desk.contracts import Behaviour, Decision
    out = []
    for msg in split_chat_dump(body.text.strip()):
        desk.agent.new_conversation()
        try:
            d = desk.handle_message(msg, requester="web")
        except BudgetExceeded:
            d = Decision(request_id="", behaviour=Behaviour.ASK,
                         explanation="Request limit reached. Please try again later.")
        except Exception:
            d = Decision(request_id="", behaviour=Behaviour.ASK,
                         explanation="Request failed. Please retry later.")
        s["decisions"][d.decision_id] = {"decision": d, "msg": msg, "skipped": False}
        out.append(d)
        _log(s, "dispatcher", msg, d.explanation)
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
        return {"error": "Unknown decision."}
    try:
        updated, record, reply = desk.follow_up(body.text, item["decision"],
                                                requester="web")
    except BudgetExceeded:
        return {"error": "Request limit reached. Please try again later."}
    except Exception:
        return {"error": "Request failed. Please retry later."}
    if record is not None:
        del s["decisions"][body.decision_id]
    elif updated is not None:
        item["decision"] = updated
    _log(s, "dispatcher", body.text, reply or "")
    _refresh_stale(s)
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
        return exc.decision, "stale"
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
    elif err is None:
        del s["decisions"][body.decision_id]
        _log(s, "dispatcher", f"(card) {body.workshop_id}",
             f"Committed {result.record_id} — {result.order_id} → {result.workshop_id}.")
    else:
        return {"error": err}
    _refresh_stale(s)
    return _state(s, sid)


class SplitBody(BaseModel):
    decision_id: str
    index: int = 0


@app.post("/api/confirm_split")
def confirm_split(body: SplitBody, request: Request):
    s, sid = _session(request)
    item = s["decisions"].get(body.decision_id)
    if item is None:
        return {"error": "Unknown decision."}
    try:
        records = s["desk"].confirm_split(item["decision"], body.index,
                                          committed_by="web")
    except ProposalChanged as exc:
        item["decision"] = exc.decision
    except ValueError as exc:
        return {"error": str(exc)}
    else:
        del s["decisions"][body.decision_id]
        _log(s, "dispatcher", f"(split #{body.index + 1})",
             f"Committed {len(records)} parts.")
    _refresh_stale(s)
    return _state(s, sid)


@app.post("/api/confirm_all")
def confirm_all(request: Request):
    s, sid = _session(request)
    open_d = [x["decision"] for x in s["decisions"].values()
              if not x["skipped"] and x["decision"].candidates
              and x["decision"].chosen]
    results, failures = s["desk"].confirm_all(open_d, committed_by="web")
    for d, record in results:
        s["decisions"].pop(d.decision_id, None)
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
    s["decisions"].pop(body.decision_id, None)
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
            item["decision"] = desk.refresh(
                replace(item["decision"], objective=body.objective))
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
    s["desk"] = DispatchDesk(stages=body.stages) if s["shared"] else _new_desk(False)
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
    st = _state(s, sid)
    st["shock_target"] = target.workshop_id
    return st


@app.delete("/api/shock")
def shock_off(request: Request):
    s, sid = _session(request)
    for w in s["desk"].workshops.workshops.values():
        if w.status == "SUSPENDED":
            w.status = "ACTIVE"
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


@app.get("/api/records")
def records(request: Request):
    s, _ = _session(request)
    return [asdict(r) for r in s["desk"].audit.load_all()]


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
