"""
api/main.py — FastAPI wrapper around DispatchDesk.

The Streamlit app is one way to serve the desk; this is the thin REST
alternative. desk/ is used as-is: no business logic lives here.

    uvicorn api.main:app --reload

Endpoints (all JSON):
    GET  /                     the static desk page
    GET  /api/health           liveness
    GET  /api/samples          dispatch*.txt in data/
    GET  /api/sample?name=     one sample inbox's text
    GET  /api/queues           live workshop queues
    GET  /api/records          committed allocations (audit ledger)
    POST /api/dispatch         {text} -> per-line Decisions (LLM rounds)
    POST /api/confirm          {decision_id, workshop_id} -> commit
    POST /api/reset            archive allocations, wipe learned performance
"""

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from desk.chat_dump import split_chat_dump
from desk.budget import BudgetExceeded
from desk.desk import DispatchDesk, ProposalChanged

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(title="Dispatch Desk API")

_desk = DispatchDesk()          # sandbox storage by default (session-local SQLite)
_decisions = {}                 # decision_id -> Decision awaiting confirmation


def _public(d):
    """Decision -> JSON the static page renders."""
    return {
        "decision_id": d.decision_id,
        "order_id": d.parsed.order_id,
        "behaviour": d.behaviour.value,
        "explanation": d.explanation,
        "warnings": list(d.warnings),
        "candidates": [
            {"workshop_id": c.workshop_id, "name": c.name,
             "estimated_finish": c.estimated_finish, "cost": c.cost,
             "defect_risk": c.defect_risk}
            for c in d.candidates
        ],
        "chosen": d.chosen.workshop_id if d.chosen else None,
        "tool_log": [{"tool": t.get("tool"),
                      "arguments": t.get("arguments")} for t in d.tool_log],
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


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


@app.get("/api/queues")
def queues():
    return dict(_desk.state.queues)


@app.get("/api/records")
def records():
    return [asdict(r) for r in _desk.audit.load_all()]


class DispatchBody(BaseModel):
    text: str


@app.post("/api/dispatch")
def dispatch(body: DispatchBody):
    from desk.contracts import Behaviour, Decision
    out = []
    for msg in split_chat_dump(body.text.strip()):
        _desk.agent.new_conversation()
        try:
            d = _desk.handle_message(msg, requester="web")
        except BudgetExceeded:
            d = Decision(request_id="", behaviour=Behaviour.ASK,
                         explanation="Request limit reached. Please try again later.")
        except Exception:
            d = Decision(request_id="", behaviour=Behaviour.ASK,
                         explanation="Request failed. Please retry later.")
        _decisions[d.decision_id] = d
        out.append(_public(d))
    return {"decisions": out}


class ConfirmBody(BaseModel):
    decision_id: str
    workshop_id: str


@app.post("/api/confirm")
def confirm(body: ConfirmBody):
    from dataclasses import replace
    d = _decisions.get(body.decision_id)
    if d is None:
        return {"error": "Unknown or already committed decision."}
    target = next((c for c in d.candidates if c.workshop_id == body.workshop_id), None)
    if target is None:
        return {"error": f"{body.workshop_id} is not a candidate."}
    try:
        record = _desk.confirm(replace(d, chosen=target), committed_by="web")
    except ProposalChanged as exc:
        _decisions[body.decision_id] = exc.decision
        return {"error": "stale", "decision": _public(exc.decision)}
    except ValueError as exc:
        return {"error": str(exc)}
    del _decisions[body.decision_id]
    return {"committed": asdict(record)}


@app.post("/api/reset")
def reset():
    _desk.audit.reset()
    _desk.performance.clear()
    _decisions.clear()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
