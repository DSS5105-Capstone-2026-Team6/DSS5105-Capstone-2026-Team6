"""api/routes/intake.py — samples, message splitting, LLM parse, dispatch."""

import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from desk.budget import BudgetExceeded
from desk.chat_dump import split_chat_dump
from desk.config import DATA_DIR
from api.state import get_session, log, refresh_stale, state_payload

router = APIRouter()


@router.get("/api/samples")
def samples():
    return sorted(p.name for p in DATA_DIR.glob("dispatch*.txt"))


@router.get("/api/sample")
def sample(name: str):
    p = DATA_DIR / name
    if p.parent != DATA_DIR or not p.exists():
        return {"error": "unknown sample"}
    return {"name": name, "text": p.read_text(encoding="utf-8")}


class SplitInboxBody(BaseModel):
    text: str


@router.post("/api/split")
def split(body: SplitInboxBody):
    """Split an inbox dump into individual messages (for per-line progress)."""
    return {"lines": split_chat_dump(body.text.strip())}


class ParseBody(BaseModel):
    text: str


@router.post("/api/parse")
def parse(body: ParseBody, request: Request):
    s, _ = get_session(request)
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


@router.post("/api/dispatch")
def dispatch(body: DispatchBody, request: Request):
    s, sid = get_session(request)
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
            log(s, "dispatcher", msg, d.explanation, decision_id=d.decision_id)
        s["timings"].append({"kind": "dispatch", "ms": round((time.perf_counter() - t0) * 1000)})
    refresh_stale(s)
    return state_payload(s, sid)
