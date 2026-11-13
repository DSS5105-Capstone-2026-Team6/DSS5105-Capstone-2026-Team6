"""Tool log popover: per-order tool calls with behaviour-coloured chips."""

from streamlit.testing.v1 import AppTest


def _app():
    import streamlit as st
    from desk.contracts import Behaviour, Candidate, Decision, ParsedRequest
    from app.components.tool_log import render_tool_log
    W6 = Candidate(workshop_id="W6", name="Nimble Needle",
                   estimated_finish="2026-04-06", days_late=0.0, cost=480.0,
                   defect_risk=0.05)
    d = Decision(request_id="R01", behaviour=Behaviour.ALLOCATE,
                 parsed=ParsedRequest(order_id="ORD-063"),
                 candidates=[W6], chosen=W6,
                 tool_log=[{"tool": "lookup_order",
                            "arguments": {"order_id": "ORD-063"},
                            "result": {"found": True}},
                           {"tool": "rank_candidates",
                            "arguments": {"objective": "hybrid"},
                            "result": {"chosen": "W6"}}],
                 explanation="ok")
    st.session_state.decisions = [{"msg": "Ravi: ORD-063", "decision": d}]
    render_tool_log()


def test_tool_log_renders_chip_and_calls():
    at = AppTest.from_function(_app).run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "ORD-063" in html
    assert "#d3f9d8" in html          # ALLOCATE green chip (theme BADGE colour)
    assert "lookup_order" in html and "rank_candidates" in html


def test_tool_log_empty_state():
    def app():
        import streamlit as st
        from app.components.tool_log import render_tool_log
        st.session_state.decisions = []
        render_tool_log()
    at = AppTest.from_function(app).run()
    assert not at.exception
    assert any("No tool calls yet" in c.value for c in at.caption)
