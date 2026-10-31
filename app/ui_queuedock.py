"""
ui_queuedock — the live-queue dock pinned to the bottom-right corner.

Streamlit has no native floating panels, so this uses a keyed container
(`st.container(key="queue_dock")`) plus a CSS rule (ui_shared.CSS, the
[class*="st-key-queue_dock"] selector) that pins it out of the flow. The
content is plain Python re-rendered on every rerun, so the bars move as
soon as any session commits a dispatch.
"""

import streamlit as st

from app.ui_shared import queue_bar_html


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
        st.markdown("**🎯 Re-rank objective**")
        pref = st.session_state.get("objective_pref", "hybrid")
        pick = st.segmented_control(
            "objective", list(OBJECTIVES), default=pref,
            key="objective_dock_sel", label_visibility="collapsed",
            disabled=locked)
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


def render_queue_dock(desk):
    """One compact line per workshop: name, live queue bar, days. Bars share
    one scale (the longest queue), so lengths are comparable at a glance."""
    queues = desk.state.queues
    scale = max(list(queues.values()) + [0.1])
    with st.container(key="queue_dock"):
        st.markdown("**📡 Live queues**")
        for wid in sorted(queues):
            w = desk.workshops.workshops[wid]
            bar = queue_bar_html(queues[wid], 0.0, scale)
            st.markdown(
                f'<div class="dock-row">'
                f'<span class="dock-name">{w.name}</span>{bar}'
                f'<span class="dock-days">{queues[wid]:.1f}d</span></div>',
                unsafe_allow_html=True)
        st.caption("updates on every interaction")
