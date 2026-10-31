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
    """The allocator's four objectives as a right-rail panel. The pick is
    stored as session_state.objective_pref and used by every card's
    🔄 Re-rank button. Default is hybrid — the production allocator."""
    from desk.allocator import OBJECTIVES
    with st.container(key="objective_dock"):
        st.markdown("**🎯 Re-rank objective**")
        pref = st.session_state.get("objective_pref", "hybrid")
        pick = st.segmented_control(
            "objective", list(OBJECTIVES), default=pref,
            key="objective_dock_sel", label_visibility="collapsed")
        if pick and pick != pref:
            st.session_state.objective_pref = pick
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
