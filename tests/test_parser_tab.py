"""LLM parser inbox tab: Dispatch stays locked until the exact text in the
box has been parsed successfully; the result renders as cards."""

from streamlit.testing.v1 import AppTest


def _app():
    from types import SimpleNamespace
    import streamlit as st
    import desk.llm_parser as lp
    from desk.register import OrderStore
    from app import ui_inbox
    lp.parse_message = lambda text, agent: {
        "orders": [{"order_id": "ORD-095", "customer": "Bright Basics", "product": "hoodies",
                    "category": "TOPS", "pieces": 800, "due_date": "2026-04-20"}],
        "intent": "allocate",
        "constraints": [{"type": "exclude", "detail": "not BudgetWorks", "imposed_by": "Boss"}]}
    desk = SimpleNamespace(agent=None, orders=OrderStore())
    text = st.text_area("msg", key="llm_parse_text")
    st.session_state.clicked = ui_inbox._parser_controls(text, desk)


def test_dispatch_locked_until_parse_and_relocked_on_edit():
    at = AppTest.from_function(_app).run()
    at.text_area(key="llm_parse_text").set_value("Ravi: ORD-095 — 800 hoodies, due Apr 20").run()
    assert at.button(key="llm_dispatch").disabled
    at.button(key="llm_parse_btn").click().run()
    assert not at.exception
    assert not at.button(key="llm_dispatch").disabled
    html = " ".join(m.value for m in at.markdown)
    assert "ORD-095" in html and "register: 2026-04-26" in html and "Exclude" in html
    at.text_area(key="llm_parse_text").set_value("something else").run()
    assert at.button(key="llm_dispatch").disabled


def test_clear_empties_box_and_result():
    at = AppTest.from_function(_app).run()
    at.text_area(key="llm_parse_text").set_value("ORD-095").run()
    at.button(key="llm_parse_btn").click().run()
    at.button(key="llm_clear").click().run()
    assert at.text_area(key="llm_parse_text").value == ""
    assert "llm_parse_result" not in at.session_state
