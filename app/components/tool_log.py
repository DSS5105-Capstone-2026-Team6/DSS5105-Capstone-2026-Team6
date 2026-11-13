"""
components.tool_log — per-order tool-call records for the worklist.

Reads the decisions currently in session_state and renders, for every order,
its behaviour chip (coloured like the inbox badges) and the tool calls the
agent made for it — the same tool log the faithfulness checker uses.
"""

import json

import streamlit as st

from desk.contracts import Behaviour
from app.theme.tokens import BADGE


def _chip(behaviour):
    label, color = BADGE[behaviour]
    return (f'<span style="background:{color};padding:1px 8px;'
            f'border-radius:8px;font-weight:600">{label}</span>')


def _args_brief(arguments):
    """One-line digest of a tool call's arguments, capped for the popover."""
    if not isinstance(arguments, dict) or not arguments:
        return ""
    parts = [f"{k}={v}" for k, v in arguments.items() if v not in (None, "", [])]
    text = ", ".join(parts)
    return text[:80] + ("…" if len(text) > 80 else "")


def render_tool_log():
    """The Tool log popover body: one section per order, tool calls inside."""
    items = st.session_state.get("decisions", [])
    logged = [(x["decision"].parsed.order_id or x["msg"][:24], x["decision"])
              for x in items if x["decision"].tool_log]
    if not logged:
        st.caption("No tool calls yet — dispatch something first.")
        return
    for i, (label, decision) in enumerate(logged, 1):
        st.markdown(
            f'<div class="one-line">{_chip(decision.behaviour)} '
            f'&nbsp;<b>{label}</b> · {len(decision.tool_log)} call(s)</div>',
            unsafe_allow_html=True)
        for call in decision.tool_log:
            brief = _args_brief(call.get("arguments"))
            st.markdown(
                f'<div class="muted" style="margin-left:10px">'
                f'· <code>{call.get("tool", "?")}</code>'
                + (f" ({brief})" if brief else "") + "</div>",
                unsafe_allow_html=True)
        with st.expander(f"Raw results · {label}", expanded=False):
            st.code(json.dumps(decision.tool_log, indent=2, default=str),
                    language="json")
        if i < len(logged):
            st.divider()
