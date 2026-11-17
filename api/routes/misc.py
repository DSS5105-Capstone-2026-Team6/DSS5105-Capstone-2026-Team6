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


@router.post("/api/compare_models")
def compare_models(body: CompareBody, request: Request):
    """Run the first `limit` dev-inbox requests through each model and score
    behaviour labels against data/labels_inbox.json."""
    from desk.chat_dump import ENVELOPE
    from desk.config import DATA_DIR
    import json as _json

    labels_path = DATA_DIR / "labels_inbox.json"
    inbox_path = DATA_DIR / "dispatch_requests.txt"
    raw = _json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else []
    labels = {x["request_id"]: x for x in raw} if isinstance(raw, list) else raw
    lines = [l for l in inbox_path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")][:max(1, body.limit)]

    out = []
    for spec in body.models:
        provider_, _, model = spec.partition(":")
        entry = {"model": spec, "provider": provider_, "results": [], "error": None}
        try:
            desk = DispatchDesk(provider=provider_, model=model or None)
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


@router.post("/api/share")
def share(body: ShareBody, request: Request):
    s, sid = get_session(request)
    s["shared"] = body.shared
    s["decisions"] = {}
    s["desk"] = DispatchDesk() if body.shared else new_desk(False)
    return state_payload(s, sid)
