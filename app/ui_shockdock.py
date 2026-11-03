"""
ui_shockdock — the right-rail world panel: start date, stages mode, and a
seeded shock trigger.

Start date moves the shared world clock (desk/config.set_as_of): April 1st
is the 30-request chat demo, January 1st is the full replay start. Stages
mode swaps the order/workshop stores to the *_stages data. Both rebuild the
desk (session prefs live in st.session_state, get_desk re-reads them).

Shock mirrors harness/simulate.py: a seeded random ACTIVE workshop is
closed (Random(seed).choice, so the same seed always closes the same shop).
Eligibility, ranking, estimates and flag_at_risk all read the same live
store, so the whole desk reacts immediately. Resolve restores ACTIVE.
"""

import random

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

        # -------- seeded shock --------
        active_shock = st.session_state.get("shock_target")
        if active_shock:
            w = desk.workshops.workshops[active_shock]
            st.warning(f"⚡ {w.name} is SUSPENDED "
                       f"(seed {st.session_state.get('shock_seed', 5105)})")
            if st.button("Resolve shock", key="shock_off",
                         use_container_width=True):
                w.status = "ACTIVE"
                st.session_state.shock_target = None
                st.rerun()
        else:
            st.caption("Shock: close a workshop picked by seed "
                       "(same seed → same shop, like the simulator).")
            st.number_input("Shock seed", value=5105, step=1,
                            key="shock_seed")
            if st.button("⚡ Trigger shock", key="shock_on",
                         use_container_width=True):
                active = [w for w in desk.workshops.workshops.values()
                          if w.status == "ACTIVE"]
                target = random.Random(
                    int(st.session_state.shock_seed)).choice(
                        sorted(active, key=lambda w: w.workshop_id))
                target.status = "SUSPENDED"
                st.session_state.shock_target = target.workshop_id
                st.rerun()
