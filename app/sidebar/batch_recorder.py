"""
sidebar.batch_recorder — the returned-batch recorder:
update_workshop_performance's UI face. Record a returned batch so the
estimator learns, and see the learned-vs-profile state per workshop.
"""

import streamlit as st


def render_performance_sidebar(desk):
    """update_workshop_performance's UI face: record a returned batch so the
    estimator learns (roadmap §1.6). Shows the learned-vs-profile state."""
    from desk.performance import MIN_SAMPLES
    from desk.tools import update_workshop_performance
    with st.sidebar.expander("Record a returned batch"):
        workshops = sorted(desk.workshops.workshops.values(),
                           key=lambda w: w.workshop_id)
        # no st.form: a form only reruns on submit, so Pieces could not
        # follow the workshop picker. Each workshop remembers its own last
        # Pieces value (rb_pieces); the other inputs keep their values too.
        with st.container(border=True):
            ws = st.selectbox("Workshop", workshops, key="rb_workshop",
                              format_func=lambda w: f"{w.name} ({w.workshop_id})")
            memory = st.session_state.setdefault("rb_pieces", {})
            pieces = st.number_input("Pieces", min_value=1, step=50,
                                     value=memory.get(ws.workshop_id, 400),
                                     key=f"rb_pieces_{ws.workshop_id}")
            memory[ws.workshop_id] = int(pieces)
            promised = st.date_input("Promised date", key="rb_promised")
            actual = st.date_input("Actual return date", key="rb_actual")
            submitted = st.button("Record", key="rb_record")
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
