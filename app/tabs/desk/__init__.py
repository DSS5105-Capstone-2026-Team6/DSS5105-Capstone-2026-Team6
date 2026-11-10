"""
tabs.desk — the Desk tab: intake -> dispatch loop -> worklist.

    intake.read_source()   the four message sources, returns (text, clicked)
    render_inbox()         the dispatch loop over the pasted lines, then the
                           worklist below (this module)
    worklist               KPI row, case filter, one expander per request
    cards                  everything one expanded request card renders
    scenario               Sunday-closure / transport-delay preview

The confirmation-flow helpers (_budget_ok, _log_exchange, _norm_msg) live
in app.streamlit_app because the safety tests exec them straight from that
file's AST — so they are imported lazily inside the functions that need
them (a top-level import would be circular).
"""

import streamlit as st

from desk.contracts import Behaviour, Decision
from desk.chat_dump import ENVELOPE, split_chat_dump
from desk.budget import BudgetExceeded

from app.tabs.desk.intake import read_source
from app.tabs.desk.worklist import render_worklist


def _save_thread(decision, desk):
    """Snapshot the agent's current thread as this item's conversation."""
    from app.streamlit_app import _norm_msg
    st.session_state[f"conv-{id(decision)}"] = [_norm_msg(m)
                                                for m in desk.agent.history]


def render_inbox(desk):
    """Feed the desk, then list what came back. The dispatch loop keeps
    each inbox line independent (fresh conversation per line) and logs one
    sidebar exchange per line."""
    from app.streamlit_app import _budget_ok, _log_exchange
    text, clicked = read_source(desk)
    if clicked and text.strip():
        msgs = split_chat_dump(text.strip())
        if _budget_ok(len(msgs)):
            st.session_state.dispatching = True   # locks the objective panel
            try:
                decisions = []
                for i, msg in enumerate(msgs, 1):
                    desk.agent.new_conversation()  # inbox lines are independent
                    with st.spinner(f"Dispatching ({i}/{len(msgs)}: {msg[:40]}...)"):
                        st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
                        try:
                            decision = desk.handle_message(msg, requester="dispatcher")
                        except BudgetExceeded:
                            decision = Decision(request_id="", behaviour=Behaviour.ASK,
                                explanation="Request limit reached. Please try again later.")
                        except Exception:
                            decision = Decision(request_id="", behaviour=Behaviour.ASK,
                                explanation="Request failed. Please retry later or check server configuration.")
                        decisions.append({"msg": msg, "decision": decision})
                        _save_thread(decision, desk)   # per-item conversation seed
                        env = ENVELOPE.match(msg)
                        _log_exchange(env.group(3) if env else "chat",
                                      env.group(4) if env else msg,
                                      decision.explanation,
                                      link=f"d{id(decision)}")
                st.session_state.decisions = decisions
            finally:
                st.session_state.dispatching = False   # unlock even on error
            # the sidebar chat log was drawn before this loop ran; rerun so
            # the new exchanges show up now, not after the next click
            st.rerun()

    items = st.session_state.get("decisions", [])
    if not items:
        st.info("Inbox is empty.")
        return
    render_worklist(desk, items)
