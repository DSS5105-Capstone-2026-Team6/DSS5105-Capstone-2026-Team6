"""
components.cards — the two leaf renderers every surface builds on: the
styled card and the animated queue bar.

Imports only streamlit, so any app module can use these safely.
"""

import streamlit as st


def card(html, delay=0.0, cls=""):
    """One card. delay staggers the entrance animation (seconds); cls adds
    classes (e.g. "chosen" for the recommended option)."""
    style = f' style="animation-delay:{delay}s"' if delay else ""
    st.markdown(f'<div class="card {cls}"{style}>{html}</div>',
                unsafe_allow_html=True)


def queue_bar_html(queue_now, queue_added, scale):
    """Inline-SVG-free queue bar: current queue (soft blue) + this order's
    expected work (deep blue) stacked, widths as % of `scale` days. The
    fills grow from 0 via the qgrow keyframe, so bars animate in on every
    rerun — and re-rendered values visibly move when queues change."""
    now_pct = round(min(100.0, 100.0 * queue_now / scale), 1) if scale else 0
    add_pct = round(min(100.0 - now_pct, 100.0 * queue_added / scale), 1) \
        if scale else 0
    return (f'<div class="qbar-track">'
            f'<div class="qbar-fill qbar-now" style="width:{now_pct}%"></div>'
            f'<div class="qbar-fill qbar-add" style="width:{add_pct}%"></div>'
            f'</div>')
