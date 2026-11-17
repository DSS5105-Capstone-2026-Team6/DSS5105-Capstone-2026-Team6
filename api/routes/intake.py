"""api/routes/intake.py — samples, message splitting, LLM parse, dispatch."""

import json as _json
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from desk.budget import BudgetExceeded
from desk.chat_dump import BARE_LINE, ENVELOPE, split_chat_dump
from desk.config import DATA_DIR
from api.state import get_session, refresh_stale, state_payload

router = APIRouter()


def _sender_of(text):
    """Who sent this message: 'R01 [07:53] Chen: …' / 'Ravi: …' -> the name."""
    m = ENVELOPE.match(text.strip())
    if m:
        return m.group(3).strip()
    if BARE_LINE.match(text.strip()):
        return text.strip().split(":", 1)[0].strip()
    return None


def _msg_meta(msg):
    """(sender, chat-log summary) for one dispatched message. JSON lines
    from the LLM parser become a compact 'ORD-045 · 150 pcs · due …'
    instead of echoing raw JSON; plain chat lines keep their full text."""
    if msg.lstrip().startswith("{"):
        try:
            o = _json.loads(msg)
            parts = [o.get("order_id") or "new order"]
            if o.get("pieces"):
                parts.append(f"{o['pieces']} pcs")
            if o.get("product"):
                parts.append(str(o["product"]))
            if o.get("due_date"):
                parts.append(f"due {o['due_date']}")
            return o.get("from"), " · ".join(parts)
        except Exception:
            pass
    return _sender_of(msg), msg


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


def _normalized_requests(out, sender=None):
    """One compact JSON line per parsed order — the inbox takes these as
    individual requests, so a message mentioning 20 orders dispatches as
    20 separate cards (constraints and the sender ride along on every line)."""
    cons = out.get("constraints") or []
    lines = []
    for o in out.get("orders") or []:
        req = {k: v for k, v in o.items()
               if k != "register" and v not in (None, "")}
        if sender:
            req["from"] = sender
        if cons:
            req["constraints"] = cons
        lines.append(_json.dumps(req, ensure_ascii=False))
    return lines


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
        normalized = _normalized_requests(out, sender=_sender_of(body.text))
        if normalized:
            out["normalized"] = normalized
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
        s["req_counter"] = 0
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
            sender, summary = _msg_meta(msg)
            s["req_counter"] = s.get("req_counter", 0) + 1
            n = s["req_counter"]
            s["decisions"][d.decision_id] = {"decision": d, "msg": msg,
                                             "skipped": False,
                                             "sender": sender, "n": n}
            s["metrics"]["dispatched"] += 1
            if d.behaviour in (Behaviour.REFUSE, Behaviour.NO_DATA):
                s["metrics"]["failed"] += 1
            out.append(d)
            # structured chat entry: "Request #3 · Boss: ORD-045 · 150 pcs …"
            s["chat_log"].append({"speaker": "request", "n": n, "user": sender,
                                  "text": summary, "reply": d.explanation,
                                  "decision_id": d.decision_id})
        s["timings"].append({"kind": "dispatch", "ms": round((time.perf_counter() - t0) * 1000)})
    refresh_stale(s)
    return state_payload(s, sid)
