"""api/routes/world.py — world date, stages, shocks, scenario preview."""

import random

from fastapi import APIRouter, Request
from pydantic import BaseModel

from desk.desk import DispatchDesk
from api.state import (PerfFacade, get_session, invalidate_ledger,
                       ledger_snapshot, state_payload, warm_caches_async)

router = APIRouter()


class WorldBody(BaseModel):
    as_of: str
    stages: bool


@router.post("/api/world")
def world(body: WorldBody, request: Request):
    from desk.config import set_as_of
    s, sid = get_session(request)
    set_as_of(body.as_of)
    s["stages"] = body.stages
    s["shock_target"] = None      # a world change clears any active shock
    if s["shared"]:
        s["desk"] = DispatchDesk(stages=body.stages)
    else:
        s["desk"] = DispatchDesk(stages=body.stages, storage_dir=s["storage_dir"])
    invalidate_ledger(s)
    warm_caches_async(s)
    return state_payload(s, sid)


class ShockBody(BaseModel):
    seed: int = 5105


@router.post("/api/shock")
def shock_on(body: ShockBody, request: Request):
    s, sid = get_session(request)
    desk = s["desk"]
    active = [w for w in desk.workshops.workshops.values() if w.status == "ACTIVE"]
    target = random.Random(body.seed).choice(sorted(active, key=lambda w: w.workshop_id))
    target.status = "SUSPENDED"
    s["shock_target"] = target.workshop_id
    s["shock_seed"] = body.seed
    return state_payload(s, sid)


@router.delete("/api/shock")
def shock_off(request: Request):
    s, sid = get_session(request)
    desk = s["desk"]
    # restore the tracked target first (the Streamlit desk does the same),
    # then any other SUSPENDED workshop
    if s["shock_target"] in desk.workshops.workshops:
        desk.workshops.workshops[s["shock_target"]].status = "ACTIVE"
    for w in desk.workshops.workshops.values():
        if w.status == "SUSPENDED":
            w.status = "ACTIVE"
    s["shock_target"] = None
    return state_payload(s, sid)


class ScenarioBody(BaseModel):
    order_id: str
    preview_date: str | None = None
    closed: bool = False
    delay: int = 0
    noise_pct: float = 0
    seed: int = 5105
    objective: str = "hybrid"


@router.post("/api/scenario")
def scenario(body: ScenarioBody, request: Request):
    from datetime import date
    from app.tabs.desk.scenario import compare_sunday
    s, _ = get_session(request)
    desk = s["desk"]
    pd_ = date.fromisoformat(body.preview_date) if body.preview_date else None
    result = compare_sunday(body.order_id, desk.orders, desk.workshops,
                            ledger_snapshot(s)[1], body.closed, body.delay,
                            perf=PerfFacade(s), noise_pct=body.noise_pct,
                            seed=body.seed, preview_date=pd_)
    if "error" in result:
        return result
    from desk.allocator import order_rows
    result["baseline_pick"] = order_rows(result["baseline"], body.objective)[0]
    result["scenario_pick"] = order_rows(result["scenario"], body.objective)[0]
    return result
