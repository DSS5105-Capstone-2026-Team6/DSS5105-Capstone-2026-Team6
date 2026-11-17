"""api/routes/decisions.py — follow-ups, confirms, skip/dismiss, rerank."""

import time
from dataclasses import replace

from fastapi import APIRouter, Request
from pydantic import BaseModel

from desk.budget import BudgetExceeded
from desk.desk import ProposalChanged
from api.state import (archive_tool_log, get_session, invalidate_ledger, log,
                       refresh_stale_async, state_payload)

router = APIRouter()


class FollowupBody(BaseModel):
    decision_id: str
    text: str


def _closed_notice(s, sid):
    st = state_payload(s, sid)
    st["reply"] = ("This request is already closed (committed or "
                   "dismissed) — there is nothing left to discuss.")
    st["notice"] = st["reply"]
    return st


@router.post("/api/followup")
def followup(body: FollowupBody, request: Request):
    s, sid = get_session(request)
    desk = s["desk"]
    item = s["decisions"].get(body.decision_id)
    if item is None:
        return _closed_notice(s, sid)
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
        archive_tool_log(s, item["decision"])
        s["metrics"]["committed"].add(record.order_id)
        del s["decisions"][body.decision_id]
        invalidate_ledger(s)
    elif updated is not None:
        # follow_up may return a NEW decision object with a NEW id — keep the
        # proposal's id stable so cards and follow-ups stay addressable
        updated.decision_id = body.decision_id
        item["decision"] = updated
    log(s, "dispatcher", body.text, reply or "", decision_id=body.decision_id)
    st = state_payload(s, sid)
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


@router.post("/api/confirm")
def confirm(body: ConfirmBody, request: Request):
    s, sid = get_session(request)
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
        archive_tool_log(s, item["decision"])
        del s["decisions"][body.decision_id]
        s["metrics"]["committed"].add(result.order_id)
        invalidate_ledger(s)
        log(s, "dispatcher", f"(card) {body.workshop_id}",
            f"Committed {result.record_id} — {result.order_id} → {result.workshop_id}.")
    else:
        return {"error": err}
    refresh_stale_async(s)   # stars catch up in the background, no freeze
    return state_payload(s, sid)


class ConfirmSplitBody(BaseModel):
    decision_id: str
    index: int = 0


@router.post("/api/confirm_split")
def confirm_split(body: ConfirmSplitBody, request: Request):
    s, sid = get_session(request)
    item = s["decisions"].get(body.decision_id)
    if item is None:
        return _closed_notice(s, sid)
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
    archive_tool_log(s, decision)
    del s["decisions"][body.decision_id]
    s["metrics"]["committed"].add(records[0].order_id)   # split = one request
    invalidate_ledger(s)
    log(s, "dispatcher", f"(split #{body.index + 1})",
        f"Committed {len(records)} parts.")
    refresh_stale_async(s)
    return state_payload(s, sid)


@router.post("/api/confirm_all")
def confirm_all(request: Request):
    s, sid = get_session(request)
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
        archive_tool_log(s, d)
        s["decisions"].pop(d.decision_id, None)
        s["metrics"]["committed"].add(record.order_id)
        log(s, "dispatcher", f"(confirm all) {d.parsed.order_id}",
            f"Committed {record.record_id}.")
    if results:
        invalidate_ledger(s)
    st = state_payload(s, sid)
    st["failures"] = failures
    return st


class IdBody(BaseModel):
    decision_id: str


@router.post("/api/skip")
def skip(body: IdBody, request: Request):
    s, sid = get_session(request)
    item = s["decisions"].get(body.decision_id)
    if item:
        item["skipped"] = True
        log(s, "dispatcher", "(skip)", f"Skipped {item['decision'].parsed.order_id}.")
    return state_payload(s, sid)


@router.post("/api/dismiss")
def dismiss(body: IdBody, request: Request):
    s, sid = get_session(request)
    item = s["decisions"].pop(body.decision_id, None)
    if item:
        archive_tool_log(s, item["decision"])
    return state_payload(s, sid)


class RerankBody(BaseModel):
    decision_id: str | None = None
    objective: str


@router.post("/api/rerank")
def rerank(body: RerankBody, request: Request):
    s, sid = get_session(request)
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
    return state_payload(s, sid)
