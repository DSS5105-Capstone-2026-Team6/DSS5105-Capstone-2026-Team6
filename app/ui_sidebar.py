"""
ui_sidebar — everything the sidebar carries: the running chat log and the
returned-batch recorder (update_workshop_performance's UI face).
"""

import streamlit as st

from app.ui_shared import _sync_anchor


def render_chat_log():
    """Sidebar record of everything the desk has handled, newest at the
    bottom. Read-only — actions live in the worklist."""
    log = st.session_state.get("chat_log", [])
    st.markdown("**💬 Chat log**")
    st.caption(f"{len(log)} messages")
    with st.container(height=420, border=False):
        for turn in log:
            with st.chat_message("user", avatar="🧑‍🔧"):
                if turn.get("link"):
                    _sync_anchor(turn["link"])
                st.write(f"**{turn['speaker']}:** {turn['text']}")
            with st.chat_message("assistant", avatar="🤖"):
                st.text(turn["reply"] if turn["reply"] else "(no reply)")


def render_performance_sidebar(desk):
    """update_workshop_performance's UI face: record a returned batch so the
    estimator learns (roadmap §1.6). Shows the learned-vs-profile state."""
    from desk.performance import MIN_SAMPLES
    from desk.tools import update_workshop_performance
    with st.sidebar.expander("📥 Record a returned batch"):
        workshops = sorted(desk.workshops.workshops.values(),
                           key=lambda w: w.workshop_id)
        with st.form("returned_batch", clear_on_submit=True):
            ws = st.selectbox("Workshop", workshops,
                              format_func=lambda w: f"{w.name} ({w.workshop_id})")
            pieces = st.number_input("Pieces", min_value=1, value=400, step=50)
            promised = st.date_input("Promised date")
            actual = st.date_input("Actual return date")
            submitted = st.form_submit_button("Record")
        if submitted:
            out = update_workshop_performance(
                ws.workshop_id, int(pieces), promised.isoformat(),
                actual.isoformat(), store=desk.workshops,
                perf=desk.performance)
            if "error" in out:
                st.error(out["error"])
            else:
                st.success(f"Recorded ({out['delay_days']}d delay). "
                           + out["note"])
                # capacity changed -> every open proposal is stale: re-rank
                # them all against the learned numbers, in one go
                from dataclasses import replace
                from desk.contracts import Behaviour
                from app.streamlit_app import _replace_item
                open_alloc = [x for x in st.session_state.get("decisions", [])
                              if x["decision"].behaviour is Behaviour.ALLOCATE
                              and x["decision"].candidates
                              and f"committed-{id(x['decision'])}" not in st.session_state]
                for x in open_alloc:
                    _replace_item(x["decision"],
                                  desk.refresh(x["decision"]),
                                  "Re-ranked: capacity estimates updated.")
        # learned-vs-profile status line per workshop with observations
        lines = []
        for w in workshops:
            learned = desk.performance.learned(w.workshop_id, profile=w)
            if learned:
                lines.append(f"**{w.workshop_id}**: learned "
                             f"{learned['eff_capacity']} pcs/day "
                             f"(profile {learned['profile_capacity']}), "
                             f"p80 delay {learned['p80_delay']}d, "
                             f"n={learned['observations']}")
        if lines:
            st.caption("Learned performance in use:")
            for line in lines:
                st.caption(line)
        else:
            st.caption(f"No learned performance yet — estimates use the "
                       f"profile card until {MIN_SAMPLES} batches per "
                       f"workshop are on file.")
