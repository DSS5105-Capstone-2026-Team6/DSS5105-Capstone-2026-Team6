"""
ui_parser — the sidebar LLM parser panel (app-side of desk/llm_parser.py).

Distinct from the rule-based inbox splitter: paste ONE freeform message and
the model returns structured extraction (orders / intent / constraints).
"Use in Dispatch" hands the same text to the normal inbox flow, so both
parsers can be compared side by side.
"""

import json

import streamlit as st

from desk.llm_parser import parse_message
from app.ui_shared import section


def render_llm_parser(desk):
    with st.sidebar.expander("LLM parser (semantic)"):
        section("LLM parser", "layers")
        text = st.text_area("One freeform message", height=90, key="llm_parse_text",
                            placeholder="Boss: ORD-045 — 150 vests for Cotton Club, due Apr 09. It's urgent.")
        if st.button("Parse", key="llm_parse_btn", use_container_width=True) and text.strip():
            with st.spinner("Parsing…"):
                st.session_state.llm_parse_result = parse_message(text, desk.agent)
        result = st.session_state.get("llm_parse_result")
        if result:
            if "error" in result:
                st.error(result["error"])
            else:
                orders = result.get("orders") or []
                st.caption(f"intent: **{result.get('intent', '?')}** · "
                           f"{len(orders)} order ref(s)")
                for o in orders:
                    st.json(o, expanded=False)
                cons = result.get("constraints") or []
                if cons:
                    st.caption("constraints: " + "; ".join(
                        f"{c.get('type')}: {c.get('detail')}"
                        + (f" (by {c['imposed_by']})" if c.get("imposed_by") else "")
                        for c in cons))
                if st.button("Use in Dispatch", key="llm_parse_dispatch",
                             use_container_width=True):
                    st.session_state.paste_box = text
                    st.session_state.inbox_src = "Paste"
                    st.rerun()
