"""
Duplicate requests, one-tap skip, and refusals that come with an alternative.

- an order already in the ledger keeps its ranking for reference, but the
  desk says so up front and marks the decision; the bot offers only "skip"
  and keeps nothing pending (a "yes" could only be refused);
- "skip" closes a request with no LLM round and no commit (bot), and the
  web card's Skip button closes it in one tap;
- a REFUSE whose flow stopped at check_eligibility gets the best eligible
  alternative ranked in code (failure case R24).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from streamlit.testing.v1 import AppTest

from adapter.session import ChatSession
from desk.confirmation import FollowupIntent, looks_like_skip
from desk.contracts import Behaviour
from desk.desk import DispatchDesk
from desk.tools import dispatch_tool


class ScriptedAgent:
    """Stands in for DispatchAgent: each chat() runs a scripted tool flow
    through the real tools, so the router sees a genuine tool log."""

    def __init__(self):
        from desk.register import WorkshopStore
        self.workshops = WorkshopStore()
        self.history, self.tool_log = [], []
        self.desk = self.budget = None
        self.flow = None          # callable(desk) -> (reply, tool_log)

    def new_conversation(self):
        self.history = []

    def classify_followup(self, text, decision):
        return FollowupIntent("other")

    def chat(self, text, verbose=False):
        reply, self.tool_log = self.flow(self.desk)
        return reply


def _rank_flow(order_id):
    def flow(desk):
        args = {"order_id": order_id, "objective": "lateness"}
        result = dispatch_tool("rank_candidates", args, desk=desk)
        return ("Reply yes to commit.",
                [{"tool": "rank_candidates", "arguments": args, "result": result}])
    return flow


def _refuse_flow(desk):
    """R24: the model looks up ORD-015 and checks eligibility, then stops."""
    log = []
    for tool, args in [("lookup_order", {"order_id": "ORD-015"}),
                       ("check_eligibility", {"category": "TOPS", "pieces": 300})]:
        log.append({"tool": tool, "arguments": args,
                    "result": dispatch_tool(tool, args, desk=desk)})
    return ("Little Loom can't take ORD-015. Want me to rank the others?", log)


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "runtime.sqlite3"))
    return DispatchDesk(agent=ScriptedAgent(), as_of="2026-04-01",
                        storage_dir=tmp_path / "sandbox")


def _commit(desk, order_id):
    desk.agent.flow = _rank_flow(order_id)
    decision = desk.handle_message(f"allocate {order_id}")
    return desk.confirm(decision, committed_by="test")


# ---------------- duplicate orders ----------------

def test_open_order_is_not_flagged(desk):
    desk.agent.flow = _rank_flow("ORD-041")
    d = desk.handle_message("allocate ORD-041")
    assert d.already_committed == ""
    assert not d.explanation.startswith("⚠️")


def test_duplicate_order_keeps_ranking_but_says_already_committed(desk):
    record = _commit(desk, "ORD-041")
    desk.agent.flow = _rank_flow("ORD-041")
    d = desk.handle_message("allocate ORD-041 again")
    assert d.already_committed == f"{record.record_id} — ORD-041 → {record.workshop_id}"
    assert d.candidates and d.chosen is not None          # recommendation kept
    assert d.explanation.startswith("⚠️ ORD-041 is already committed")
    assert d.warnings[0].startswith("Already committed")


def test_duplicate_still_cannot_commit(desk):
    _commit(desk, "ORD-041")
    desk.agent.flow = _rank_flow("ORD-041")
    d = desk.handle_message("allocate ORD-041 again")
    with pytest.raises(ValueError, match="already committed"):
        desk.confirm(d, committed_by="test")
    assert len(desk.audit.load_all()) == 1


def test_bot_duplicate_offers_only_skip_and_keeps_nothing_pending(desk):
    _commit(desk, "ORD-041")
    session = ChatSession(lambda: desk)
    desk.agent.flow = _rank_flow("ORD-041")
    reply, options = session.handle("allocate ORD-041", "Ravi")
    assert options == ["skip"]
    assert session.pending is None and session.pending_all == []
    assert reply.startswith("⚠️ ORD-041 is already committed")


def test_bot_skip_button_closes_without_llm_or_commit(desk):
    _commit(desk, "ORD-041")
    session = ChatSession(lambda: desk)
    desk.agent.flow = _rank_flow("ORD-041")
    session.handle("allocate ORD-041", "Ravi")
    desk.agent.flow = lambda _: pytest.fail("skip must not reach the model")
    reply, options = session.handle_option(session.options_token, 0, "Ravi")
    assert reply.startswith("Skipped") and options == []
    assert len(desk.audit.load_all()) == 1


def test_bot_skip_drops_an_open_proposal(desk):
    session = ChatSession(lambda: desk)
    desk.agent.flow = _rank_flow("ORD-041")
    session.handle("allocate ORD-041", "Ravi")
    assert session.pending is not None
    reply, _ = session.handle("skip", "Ravi")
    assert reply == "Skipped ORD-041 — nothing was committed."
    assert session.pending is None and session.pending_all == []
    reply, _ = session.handle("yes", "Ravi")              # nothing left to commit
    assert "Nothing is awaiting confirmation" in reply
    assert desk.audit.load_all() == []


def test_skip_words():
    assert looks_like_skip("Skip") and looks_like_skip("skip this one.")
    assert looks_like_skip("跳过")
    assert not looks_like_skip("skip W6 and use W2")


# ---------------- refusal with an alternative ----------------

def test_refusal_comes_with_best_eligible_alternative(desk):
    desk.agent.flow = _refuse_flow
    d = desk.handle_message("Little Loom does lovely work — ORD-015 to them?")
    assert d.behaviour is Behaviour.REFUSE
    assert d.candidates and d.chosen is not None
    assert "W4" not in {c.workshop_id for c in d.candidates}   # Little Loom
    assert d.tool_log[-1]["called_by"] == "desk"
    assert f"Reply yes to commit ORD-015 to {d.chosen.workshop_id}" in d.explanation


def test_refusal_alternative_can_be_committed(desk):
    desk.agent.flow = _refuse_flow
    d = desk.handle_message("Little Loom does lovely work — ORD-015 to them?")
    record = desk.confirm(d, committed_by="test")
    assert (record.order_id, record.workshop_id) == ("ORD-015", d.chosen.workshop_id)


def test_refusal_stays_a_refusal_after_a_refresh(desk):
    desk.agent.flow = _refuse_flow
    d = desk.handle_message("Little Loom does lovely work — ORD-015 to them?")
    _commit(desk, "ORD-041")                              # ledger moves on
    assert desk.refresh(d).behaviour is Behaviour.REFUSE


def test_failure_case_without_order_gets_no_alternative(desk):
    def flow(desk):
        args = {"category": "TOPS", "pieces": 300}
        return ("Which order?", [{"tool": "check_eligibility", "arguments": args,
                                  "result": dispatch_tool("check_eligibility", args,
                                                          desk=desk)}])
    desk.agent.flow = flow
    d = desk.handle_message("Little Loom for the vests?")
    assert not d.candidates


# ---------------- web: one-tap skip ----------------

def _card_app():
    from types import SimpleNamespace
    import streamlit as st
    from desk.contracts import Behaviour, Decision, ParsedRequest
    from app.tabs.desk.cards import render_decision
    if "d" not in st.session_state:
        st.session_state.d = Decision(request_id="R02", behaviour=Behaviour.NO_DATA,
                                      parsed=ParsedRequest(order_id=None),
                                      explanation="No such order.")
    desk = SimpleNamespace(audit=SimpleNamespace(load_all=lambda: []))
    render_decision(st.session_state.d, desk)


def test_card_without_anything_to_confirm_has_skip():
    at = AppTest.from_function(_card_app).run()
    assert not at.exception
    assert "⏭ Skip" in [b.label for b in at.button]


def test_skip_closes_the_card_and_undo_reopens_it():
    at = AppTest.from_function(_card_app).run()
    next(b for b in at.button if b.label == "⏭ Skip").click().run()
    assert not at.exception
    assert any("Skipped" in c.value for c in at.caption)
    assert any("(skip)" in e["text"] for e in at.session_state["chat_log"])
    next(b for b in at.button if b.label == "↩ Undo").click().run()
    assert "⏭ Skip" in [b.label for b in at.button]
