"""
rail.queues — the right-rail live-queue dock.

The body runs as an st.fragment (Streamlit 1.66): it re-renders on its own
clock, so the bars move within seconds of any commit — no full page rerun
needed.
"""

import streamlit as st

from app.components.cards import queue_bar_html
from app.theme.icons import section

REFRESH_S = 5   # the queue dock's own refresh clock


@st.fragment(run_every=REFRESH_S)
def _queue_dock_body(desk):
    queues = desk.state.queues
    scale = max(list(queues.values()) + [0.1])
    for wid in sorted(queues):
        w = desk.workshops.workshops[wid]
        bar = queue_bar_html(queues[wid], 0.0, scale)
        st.markdown(
            f'<div class="dock-row">'
            f'<span class="dock-name">{w.name}</span>{bar}'
            f'<span class="dock-days">{queues[wid]:.1f}d</span></div>',
            unsafe_allow_html=True)
    st.caption(f"live · refreshes every {REFRESH_S}s")


def render_queue_dock(desk):
    """One compact line per workshop: name, live queue bar, days. Bars share
    one scale (the longest queue), so lengths are comparable at a glance."""
    with st.container(key="queue_dock"):
        section("Live queues", "activity")
        _queue_dock_body(desk)
