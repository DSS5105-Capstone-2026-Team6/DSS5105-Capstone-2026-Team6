"""api/routes/misc.py — provider switching, model comparison, shared-DB toggle."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from desk.config import PROVIDERS
from desk.desk import DispatchDesk
from api.state import get_session, new_desk, state_payload

router = APIRouter()


class ProviderBody(BaseModel):
    provider: str
    model: str | None = None


@router.post("/api/provider")
def provider(body: ProviderBody, request: Request):
    s, sid = get_session(request)
    if body.provider not in PROVIDERS:
        return {"error": f"unknown provider {body.provider}"}
    try:
        new_desk_ = (DispatchDesk(provider=body.provider, model=body.model)
                     if s["shared"]
                     else DispatchDesk(provider=body.provider, model=body.model,
                                       storage_dir=s["storage_dir"]))
    except Exception as exc:
        # keep the old desk; the UI must not lose state on a bad key
        return {"error": f"Cannot switch to {body.provider}: {exc}"}
    s["provider"] = body.provider
    s["model"] = body.model
    s["desk"] = new_desk_
    return state_payload(s, sid)


class CompareBody(BaseModel):
    models: list[str] = []      # ["deepseek:deepseek-chat", "openai:gpt-6-luna"]
    limit: int = 3


COMPARE_FILES = [   # request pool -> its label file
    ("dispatch_requests.txt", "labels_inbox.json"),
    ("dispatch_requests_full120.txt", "f_heldout.json"),
    ("dispatch_requests_heldout.txt", "labels_heldout.json"),
]


class ComparePickBody(BaseModel):
    n: int = 8
    seed: int | None = None


@router.post("/api/compare_pick")
def compare_pick(body: ComparePickBody):
    """Random requests across all three inboxes, with labels where they
    exist — the UI animates the pick, then scores each model per request."""
    import json as _json
    import random
    from desk.chat_dump import ENVELOPE
    from desk.config import DATA_DIR
    pool = []
    for fname, lname in COMPARE_FILES:
        fpath = DATA_DIR / fname
        if not fpath.exists():
            continue
        labels = {}
        if lname and (DATA_DIR / lname).exists():
            raw = _json.loads((DATA_DIR / lname).read_text(encoding="utf-8"))
            labels = {x["request_id"]: x for x in raw}
        lines = [l for l in fpath.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
        for i, line in enumerate(lines):
            m = ENVELOPE.match(line)
            rid = m.group(1) if m else f"{fname}#{i + 1}"
            lab = labels.get(rid) or {}
            pool.append({"rid": rid, "source": fname, "line_no": i + 1,
                         "text": line, "expected": lab.get("behaviour"),
                         "note": lab.get("note")})
    rng = random.Random(body.seed) if body.seed is not None else random.Random()
    # stratified: if any pool requests lack labels, take at most half the
    # picks from them so every run still has something to score; when all
    # pools are labelled (they now are) this is just a uniform draw.
    labeled = [r for r in pool if r["expected"]]
    unlabeled = [r for r in pool if not r["expected"]]
    n = min(max(1, body.n), len(pool))
    n_unl = min(len(unlabeled), n // 2)
    n_lab = min(len(labeled), n - n_unl)
    n_unl = min(len(unlabeled), n - n_lab)   # top up if labelled ran short
    picked = rng.sample(labeled, n_lab) + rng.sample(unlabeled, n_unl)
    rng.shuffle(picked)
    return {"requests": picked, "pool": len(pool),
            "labeled_pool": len(labeled),
            "files": [f for f, _ in COMPARE_FILES]}


class CompareRunBody(BaseModel):
    model: str                 # "provider:model"
    text: str
    rid: str = ""


@router.post("/api/compare_run")
def compare_run(body: CompareRunBody):
    """Classify ONE request with ONE model. A fresh desk per call: compare
    requests are independent, and separate desks are what lets the UI run
    several classifications concurrently (agent history is not thread-safe).
    Compare calls get a tighter LLM timeout than the desk default — mixed
    pools include hard cases (impossible/unanswerable) where a slow provider
    burns the full 120s x 3 attempts per round and the run feels stuck."""
    import os
    from desk.agent import DispatchAgent, load_api_key
    from desk.budget import BudgetExceeded
    from openai import OpenAI
    provider_, _, model = body.model.partition(":")
    try:
        spec = PROVIDERS[provider_]
        client = OpenAI(api_key=load_api_key(provider_),
                        base_url=spec["base_url"],
                        timeout=float(os.environ.get("COMPARE_LLM_TIMEOUT", "60")),
                        max_retries=int(os.environ.get("COMPARE_LLM_RETRIES", "1")))
        agent = DispatchAgent(model=model or None, provider=provider_, client=client)
        desk = DispatchDesk(agent=agent)
    except Exception as exc:
        return {"error": f"Cannot start {body.model}: {exc}"}
    try:
        d = desk.handle_message(body.text, requester="compare")
    except BudgetExceeded:
        return {"error": "Request limit reached. Please try again later."}
    except Exception as exc:
        return {"error": str(exc)[:200]}
    return {"got": d.behaviour.value, "explanation": d.explanation[:600]}


class ShareBody(BaseModel):
    shared: bool


@router.post("/api/share")
def share(body: ShareBody, request: Request):
    s, sid = get_session(request)
    s["shared"] = body.shared
    s["decisions"] = {}
    s["desk"] = DispatchDesk() if body.shared else new_desk(False)
    return state_payload(s, sid)
