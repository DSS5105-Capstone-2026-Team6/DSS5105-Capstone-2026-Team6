"""
tabs.desk.intake — the Desk tab's four message sources: group-chat paste,
file upload, sample inbox, and the LLM parser controls.

read_source() draws the source picker and returns (text, dispatch_clicked);
what happens with the text (the dispatch loop) lives in tabs/desk.
"""

import streamlit as st


def _parser_controls(text, desk):
    """LLM parser tab: Parse | Dispatch | Clear. Dispatch unlocks only
    after a successful parse of exactly the text now in the box; the
    parse result is drawn as cards below the buttons. Returns True when
    Dispatch was clicked."""
    from desk.llm_parser import parse_message
    from app.components.parser_view import render_parse_result
    b_parse, b_send, b_clear = st.columns([2, 4, 1])
    # never disabled: a text area only sends its value on blur / Ctrl+Enter,
    # so "disabled while empty" kept Parse grey right after typing. The
    # click itself blurs the box, and this run already sees the new text.
    if b_parse.button("Parse", use_container_width=True, key="llm_parse_btn"):
        if not text.strip():
            st.warning("Type or paste a message first.")
        else:
            with st.spinner("Parsing…"):
                st.session_state.llm_parse_result = parse_message(text, desk.agent)
                st.session_state.llm_parsed_text = text
    result = st.session_state.get("llm_parse_result")
    parsed_ok = (result is not None and "error" not in result
                 and st.session_state.get("llm_parsed_text") == text and text.strip())

    def clear():
        st.session_state.llm_parse_text = ""
        st.session_state.pop("llm_parse_result", None)
        st.session_state.pop("llm_parsed_text", None)
    b_clear.button("Clear", use_container_width=True, key="llm_clear", on_click=clear)
    clicked = b_send.button("Dispatch", use_container_width=True, type="primary",
                            key="llm_dispatch", disabled=not parsed_ok,
                            help=None if parsed_ok else "Parse this message first")
    if result is not None:
        if st.session_state.get("llm_parsed_text") != text:
            st.caption("The message changed since the last parse — parse again "
                       "to unlock Dispatch.")
        render_parse_result(result, desk.orders)
    return clicked


def read_source(desk):
    """The source picker and its input widgets. Returns (text, clicked):
    the message text to dispatch and whether Dispatch was pressed."""
    st.caption("Feed the desk — paste group-chat lines, drop a file, load a sample "
               "inbox, or let the LLM parse one message first.")
    src = st.segmented_control(
        "source", ["Group chat", "Upload file", "Sample inbox", "LLM parser"],
        default="Group chat", label_visibility="collapsed", key="inbox_src")
    text = ""
    if src == "LLM parser":
        text = st.text_area("One freeform message — Parse first, then Dispatch",
                            height=120, key="llm_parse_text",
                            placeholder="Boss: ORD-045 — 150 vests for Cotton Club, "
                                        "due Apr 09. It's urgent.")
    elif src == "Group chat":
        text = st.text_area("Paste group-chat messages", height=120,
                            placeholder="Ravi: ORD-063 — 100 cardigans, make Apr 29.",
                            key="paste_box")
    elif src == "Upload file":
        up = st.file_uploader("Drop a .txt chat dump here", type=["txt"],
                              key="inbox_file")
        if up is not None:
            text = up.getvalue().decode("utf-8")
            st.caption(f"{up.name} — {len(text.splitlines())} lines")
    else:
        from desk.config import DATA_DIR
        # any dispatch*.txt in data/ is a loadable inbox: the dev 30, the
        # held-out 20, and future full sets (120 requests)
        samples = sorted(DATA_DIR.glob("dispatch*.txt"))
        labels = {p.name: f"{p.stem} · "
                  + str(sum(1 for line in p.read_text(encoding='utf-8').splitlines()
                            if line.strip() and not line.startswith('#')))
                  + " requests" for p in samples}
        choice = st.selectbox("Sample inbox", list(labels),
                              format_func=lambda n: labels[n],
                              key="inbox_sample")
        text = (DATA_DIR / choice).read_text(encoding="utf-8")
        st.caption(f"{choice} loaded")
    if src == "LLM parser":
        clicked = _parser_controls(text, desk)
    else:
        b_send, b_clear = st.columns([5, 1])
        # Clear empties the paste box only; results and the chat log stay
        if src == "Group chat":
            b_clear.button("Clear", use_container_width=True,
                           on_click=lambda: st.session_state.update(paste_box=""))
        clicked = b_send.button("Dispatch", use_container_width=True, type="primary")
    return text, clicked
