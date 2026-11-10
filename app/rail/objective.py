"""
rail.objective — the right-rail objective picker: the allocator's four
objectives plus the global re-rank.

The objective locks ONLY while a dispatch run is in progress; once the
decisions are out, switching is free.
"""

import streamlit as st

from app.theme.icons import section


def render_objective_dock(desk):
    """The allocator's four objectives as a right-rail panel, plus the
    global re-rank. The objective locks ONLY while a dispatch run is in
    progress (the inbox loop is mid-flight) — once the decisions are out,
    switching is free; the global button re-ranks every open card
    atomically so a switch never leaves half the cards on each objective."""
    from dataclasses import replace
    from desk.allocator import OBJECTIVES
    from desk.contracts import Behaviour
    from app.streamlit_app import _log_exchange, _replace_item
    items = st.session_state.get("decisions", [])
    open_items = [x for x in items
                  if x["decision"].behaviour is Behaviour.ALLOCATE
                  and x["decision"].candidates
                  and f"committed-{id(x['decision'])}" not in st.session_state]
    locked = bool(st.session_state.get("dispatching"))
    with st.container(key="objective_dock"):
        section("Re-rank objective", "target")
        pref = st.session_state.get("objective_pref", "hybrid")
        # custom 2x2 grid instead of st.segmented_control: its pill style
        # wraps and clips inside the narrow rail
        pick = None
        for row in (OBJECTIVES[:2], OBJECTIVES[2:]):
            cols = st.columns(2)
            for col, obj in zip(cols, row):
                if col.button(obj, key=f"objgrid-{obj}",
                              use_container_width=True,
                              type="primary" if obj == pref else "secondary",
                              disabled=locked):
                    pick = obj
        if pick and pick != pref:
            st.session_state.objective_pref = pick
            st.rerun()
        if locked:
            st.caption("dispatching… objective is locked until the run finishes")
        if open_items and not locked:
            if st.button(f"🔄 Re-rank all ({pref})",
                         key="rerank_all", use_container_width=True):
                for x in open_items:
                    d = x["decision"]
                    fresh = desk.refresh(replace(d, objective=pref))
                    _replace_item(d, fresh, f"Re-ranked by {pref}.")
                _log_exchange("dispatcher", f"(re-rank all) {pref}",
                              f"Re-ranked {len(open_items)} open dispatch(es) "
                              f"by {pref}.")
                st.rerun()
