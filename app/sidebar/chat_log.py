"""
sidebar.chat_log — the sidebar's running record of everything the desk has
handled, newest at the bottom. Read-only — actions live in the worklist.
"""

import streamlit as st

from app.theme.icons import section
from app.theme.motion import _sync_anchor


def render_chat_log():
    """Sidebar record of everything the desk has handled, newest at the
    bottom. Read-only — actions live in the worklist."""
    log = st.session_state.get("chat_log", [])
    section("Chat log", "message")
    st.caption(f"{len(log)} messages")
    with st.container(height=420, border=False):
        for turn in log:
            with st.chat_message("user", avatar="🧑‍🔧"):
                if turn.get("link"):
                    _sync_anchor(turn["link"])
                st.write(f"**{turn['speaker']}:** {turn['text']}")
            with st.chat_message("assistant", avatar="🤖"):
                st.text(turn["reply"] if turn["reply"] else "(no reply)")
