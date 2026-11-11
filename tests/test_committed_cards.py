"""A card whose order is already in the ledger (committed on another card
or earlier) must say so and show no commit buttons."""

from streamlit.testing.v1 import AppTest


def _app(committed):
    from types import SimpleNamespace
    import streamlit as st
    from desk.contracts import Behaviour, Decision, ParsedRequest
    from app.tabs.desk.cards import render_decision
    recs = ([SimpleNamespace(record_id=f"A-003{i}", order_id="ORD-103",
                             workshop_id=w, pieces=n)
             for i, (w, n) in enumerate([("W2", 514), ("W4", 834), ("W6", 652)])]
            if committed else [])
    desk = SimpleNamespace(audit=SimpleNamespace(load_all=lambda: recs))
    d = Decision(request_id="R20", behaviour=Behaviour.IMPOSSIBLE,
                 parsed=ParsedRequest(order_id="ORD-103"))
    render_decision(d, desk)
    st.write("end")


def test_card_of_committed_order_shows_notice_and_no_buttons():
    at = AppTest.from_function(_app, kwargs={"committed": True}).run()
    assert not at.exception
    assert any("Already committed" in i.value and "W2 (514 pcs)" in i.value
               for i in at.info)
    # no commit buttons — only the one-tap skip for the duplicate request
    assert [b.label for b in at.button] == ["⏭ Skip"]


def test_card_of_open_order_has_no_notice():
    at = AppTest.from_function(_app, kwargs={"committed": False}).run()
    assert not at.exception
    assert not any("Already committed" in i.value for i in at.info)
