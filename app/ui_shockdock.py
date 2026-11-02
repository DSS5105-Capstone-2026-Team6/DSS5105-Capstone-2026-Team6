"""
ui_shockdock — the right-rail world panel: start date, stages mode, and a
manual shock trigger.

Start date moves the shared world clock (desk/config.set_as_of): April 1st
is the 30-request chat demo, January 1st is the full replay start. Stages
mode swaps the order/workshop stores to the *_stages data. Both rebuild the
desk (session prefs live in st.session_state, get_desk re-reads them).

Shock flips a workshop's status to SUSPENDED in the live WorkshopStore —
eligibility, ranking, estimates and flag_at_risk all read the same store,
so the whole desk reacts immediately. Resolve restores ACTIVE.
"""

import streamlit as st

from desk import config
from app.ui_shared import section


def render_shockdock(desk):
    with st.container(key="shock_dock"):
        section("World & shock", "zap")

        current_asof = st.session_state.get("as_of", config.CHAT_AS_OF)
        current_stages = bool(st.session_state.get("stages_pref", False))
        pick = st.selectbox(
            "Start date", list(config.AS_OF_OPTIONS),
            index=list(config.AS_OF_OPTIONS).index(current_asof)
            if current_asof in config.AS_OF_OPTIONS else 0,
            format_func=lambda d: ("April 1st · demo inbox"
                                   if d == "2026-04-01"
                                   else "January 1st · full replay"),
            key="as_of_sel")
        stages = st.checkbox("Stages mode", value=current_stages,
                             key="stages_sel")
        if (pick, stages) != (current_asof, current_stages):
            st.session_state.as_of = pick
            st.session_state.stages_pref = stages
            st.session_state.desk = None      # force rebuild in the new world
            st.rerun()

        st.caption("Shock: suspend a workshop live — eligibility, ranking "
                   "and at-risk react immediately.")
        shops = sorted(desk.workshops.workshops.values(),
                       key=lambda w: w.workshop_id)
        target = st.selectbox("Shock target", shops,
                              format_func=lambda w: f"{w.name} ({w.status})",
                              key="shock_target")
        c_on, c_off = st.columns(2)
        if c_on.button("Trigger", key="shock_on", use_container_width=True,
                       disabled=target.status != "ACTIVE"):
            target.status = "SUSPENDED"
            st.rerun()
        if c_off.button("Resolve", key="shock_off", use_container_width=True,
                        disabled=target.status == "ACTIVE"):
            target.status = "ACTIVE"
            st.rerun()
