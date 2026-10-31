"""
ui_dashboard — the 📊 tab: four views of the system at work that the
worklist and the right rail cannot show.

  📈 Queue timeline     per-workshop queue trajectory, from the ledger
  🎯 Allocator lens     one order through the hybrid's eyes (plateau + due)
  🧪 Learned drift      learned vs profile capacity (update_workshop_performance)
  🧬 Objective map      cost × defect bubbles (the allocator's trade space)
"""

import streamlit as st

from app.ui_shared import BLUE_DEEP, BLUE_PALE, BLUE_SOFT


def _queue_timeline(desk):
    """Queue trajectory per workshop, replayed from the audit ledger — every
    commit is a step point (queue_after), the first point is its queue_before."""
    import altair as alt
    import pandas as pd
    records = desk.audit.load_all()
    if not records:
        st.caption("Queue timeline appears after the first commit — every "
                   "commit is a step point here.")
        return
    points = []
    # every line starts at the 1-Apr snapshot, so a workshop with a single
    # commit still spans the chart (two same-timestamp points draw nothing)
    seen = set()
    for r in records:
        wname = desk.workshops.workshops[r.workshop_id].name
        if r.workshop_id not in seen:
            seen.add(r.workshop_id)
            points.append({"t": "2026-04-01T00:00:00+00:00",
                           "queue": desk.workshops.workshops[r.workshop_id].queue0,
                           "workshop": wname})
        points.append({"t": r.committed_at, "queue": r.queue_before,
                       "workshop": wname})
        points.append({"t": r.committed_at, "queue": r.queue_after,
                       "workshop": wname})
    df = pd.DataFrame(points)
    st.markdown("**📈 Queue timeline** — how each workshop's load evolved "
                "with every commit")
    chart = alt.Chart(df).mark_line(interpolate="step-after",
                                    strokeWidth=2).encode(
        x=alt.X("t:T", title="committed at", axis=alt.Axis(grid=False)),
        y=alt.Y("queue:Q", title="Queue (days)"),
        color=alt.Color("workshop:N", legend=alt.Legend(orient="bottom",
                                                        title=None)),
        tooltip=["workshop:N", "t:T",
                 alt.Tooltip("queue:Q", title="queue (d)")])
    st.altair_chart(chart.interactive(), use_container_width=True)


def _allocator_lens(desk):
    """One order through the allocator's eyes: E[finish] per candidate, the
    due line, the plateau band and the chosen shop — the hybrid made visible."""
    import altair as alt
    import pandas as pd
    from dataclasses import replace
    from desk.allocator import rank_candidates
    orders = [r["order_id"] for r in desk.orders.orders
              if r.get("status") != "COMPLETE"]
    oid = st.selectbox("Order under the lens", orders,
                       key="lens_order")
    objective = st.session_state.get("objective_pref", "hybrid")
    result = rank_candidates(oid, objective=objective, orders=desk.orders,
                             store=desk.workshops, queues=desk.state.queues)
    if "error" in result or not result["candidates"]:
        st.info(result.get("error", "No eligible workshop."))
        return
    rows = result["candidates"]
    rec = desk.orders.by_id(oid)
    df = pd.DataFrame({
        "workshop": [f"{r['name']} ({r['workshop_id']})" for r in rows],
        "finish": [r["est_finish_days"] for r in rows],
        "days_late": [r["expected_days_late"] for r in rows],
        "chosen": [r["workshop_id"] == result["chosen"] for r in rows]})
    from datetime import date
    from desk.tools import CHAT_TODAY
    slack = (date.fromisoformat(rec["due_date"]) - CHAT_TODAY).days
    st.markdown(f"**🎯 Allocator lens** — {oid}, objective **{objective}** "
                f"(live queues)")
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("workshop:N", sort=None, title=None,
                axis=alt.Axis(labelAngle=0)),
        y=alt.Y("finish:Q", title="expected finish (days)"),
        color=alt.condition("datum.chosen", alt.value(BLUE_DEEP),
                            alt.value(BLUE_PALE)),
        tooltip=["workshop:N", "finish:Q", "days_late:Q"])
    due = alt.Chart(pd.DataFrame({"slack": [slack]})).mark_rule(
        color="#fa5252", strokeDash=[6, 3]).encode(y="slack:Q")
    st.altair_chart((bars + due).interactive(), use_container_width=True)
    st.caption(f"red dashed line = due date (due {rec['due_date']}); the deep "
               "bar is the chosen workshop. Bars above the line finish late.")


def _learned_drift(desk):
    """Capacity view per workshop — always rendered. The toggle switches
    between the profile card and the CURRENT effective capacity (learned
    once a workshop crosses the observation threshold, profile until then);
    colours mark which source each bar actually is."""
    import altair as alt
    import pandas as pd
    from desk.performance import MIN_SAMPLES
    st.markdown("**🧪 Capacity: profile vs learned**")
    view = st.segmented_control(
        "capacity view", ["current", "profile"], default="current",
        key="drift_view", label_visibility="collapsed")
    rows, pending = [], []
    for wid, w in sorted(desk.workshops.workshops.items()):
        learned = desk.performance.learned(wid, profile=w)
        n = len(desk.performance._samples(wid))
        if learned:
            status = "learned"
            current = learned["eff_capacity"]
        elif n:
            status = f"observing {n}/{MIN_SAMPLES}"
            current = w.capacity
            pending.append(f"{w.name} {n}/{MIN_SAMPLES}")
        else:
            status = "profile"
            current = w.capacity
        rows.append({"workshop": w.name, "status": status,
                     "capacity": current if view == "current" else w.capacity})
    df = pd.DataFrame(rows)
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("workshop:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("capacity:Q", title=f"capacity (pcs/day) — {view}"),
        color=alt.Color("status:N", legend=alt.Legend(orient="bottom",
                                                      title=None),
                        scale=alt.Scale(domain=["learned", "profile"],
                                        range=[BLUE_DEEP, BLUE_PALE])),
        tooltip=["workshop:N", "status:N", "capacity:Q"])
    st.altair_chart(chart.interactive(), use_container_width=True)
    if pending:
        st.caption("Observing: " + ", ".join(pending) +
                   " — learned capacity activates at the threshold")


def _objective_map(desk):
    """Cost × defect bubbles (size = live queue) — the trade space the
    objectives navigate."""
    import altair as alt
    import pandas as pd
    names, live, cost, defect = [], [], [], []
    for wid, w in desk.workshops.workshops.items():
        names.append(w.name)
        live.append(round(desk.state.queues[wid], 2))
        cost.append(w.cost)
        defect.append(w.defect_rate)
    trade = pd.DataFrame({"cost_per_pc": cost, "defect_rate": defect,
                          "queue_days": live, "workshop": names})
    st.markdown("**🧬 Objective map** — cost × defect (bubble = live queue)")
    base = alt.Chart(trade).encode(
        x=alt.X("cost_per_pc:Q", title="Cost ($/pc)",
                axis=alt.Axis(grid=False)),
        y=alt.Y("defect_rate:Q", title="Defect rate",
                axis=alt.Axis(grid=True)))
    bubbles = base.mark_circle(color=BLUE_SOFT).encode(
        size=alt.Size("queue_days:Q", title="queue_days",
                      legend=alt.Legend(orient="bottom", offset=5,
                                        titlePadding=0.5)),
        tooltip=["workshop:N", "cost_per_pc:Q", "defect_rate:Q",
                 "queue_days:Q"])
    labels = base.mark_text(align="left", dx=10).encode(text="workshop:N")
    st.altair_chart((bubbles + labels).interactive(),
                    use_container_width=True)


def render_dashboard(desk):
    _queue_timeline(desk)
    _allocator_lens(desk)
    _learned_drift(desk)
    _objective_map(desk)
