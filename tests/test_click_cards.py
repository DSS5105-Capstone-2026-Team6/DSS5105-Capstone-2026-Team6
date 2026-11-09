"""Candidate and split cards are the confirm buttons: no separate Confirm
section, and one click on a card commits it."""

from streamlit.testing.v1 import AppTest


def _app(order_id, db):
    import streamlit as st
    from desk.agent import DispatchAgent
    from desk.contracts import Behaviour, Decision, ParsedRequest
    from desk.desk import DispatchDesk
    from app.ui_cards import render_decision
    if "desk" not in st.session_state:
        d = DispatchDesk(audit_path=db, agent=DispatchAgent(provider="deepseek", client=object()))
        st.session_state.desk = d
        st.session_state.dec = d.refresh(Decision(
            request_id="", behaviour=Behaviour.ALLOCATE,
            parsed=ParsedRequest(order_id=order_id), state_version="x"))
    render_decision(st.session_state.dec, st.session_state.desk)


def _run(order_id, tmp_path, monkeypatch):
    monkeypatch.setenv("DISPATCH_DB_PATH", str(tmp_path / "perf.sqlite3"))
    return AppTest.from_function(_app, args=(order_id, str(tmp_path / "audit.sqlite3"))).run()


def test_candidate_card_commits_in_one_click(tmp_path, monkeypatch):
    at = _run("ORD-063", tmp_path, monkeypatch)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert not any("recommended" in label for label in labels)   # old Confirm buttons gone
    assert "Re-rank" in " ".join(labels) and "Dismiss" in " ".join(labels)
    next(b for b in at.button if b.label.startswith("Confirm ")).click().run()
    assert any("Committed" in s.value for s in at.success)


def test_split_card_commits_every_part(tmp_path, monkeypatch):
    at = _run("ORD-107", tmp_path, monkeypatch)
    assert not at.exception
    next(b for b in at.button if b.label == "Confirm split #1").click().run()
    assert any("Committed" in s.value and "+" in s.value for s in at.success)
