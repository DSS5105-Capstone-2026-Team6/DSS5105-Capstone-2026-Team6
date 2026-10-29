"""
ui_dashboard — the 📊 tab: queue levels and the cost × defect bubble chart.
"""

import streamlit as st

from app.ui_shared import BLUE_DEEP, BLUE_PALE, BLUE_SOFT


def render_dashboard(desk):
    st.caption("Live chat-side queue = 2026-04-01 snapshot + what "
               "all sessions have committed. Bars update on the next interaction.")
    import pandas as pd

    names, snapshot, live, cost, defect = [], [], [], [], []
    for wid, w in desk.workshops.workshops.items():
        names.append(w.name)
        snapshot.append(w.queue0)
        live.append(round(desk.state.queues[wid], 2))
        cost.append(w.cost)
        defect.append(w.defect_rate)

    st.markdown("**📡 Workshop queue levels**")
    # Same spec st.bar_chart builds (grid, legend, tooltip, zoom/pan),
    # except: one stacked column (April 1 queue at the bottom, what all
    # sessions committed on top, so the full height = live queue) and
    # horizontal labels
    import altair as alt
    series = ["Queue on April 1", "Live queue"]
    added = [round(max(0.0, lv - s0), 2) for lv, s0 in zip(live, snapshot)]
    queues = pd.DataFrame({"workshop": names * 2,
                           "series": [series[0]] * len(names)
                                     + [series[1]] * len(names),
                           "order": [0] * len(names) + [1] * len(names),
                           "value": snapshot + added})
    chart = alt.Chart(queues).mark_bar().encode(
        x=alt.X("workshop:O", sort=None, title="Workshop",
                axis=alt.Axis(grid=False, labelAngle=0)),
        y=alt.Y("value:Q", title="Queue (days)",
                axis=alt.Axis(grid=True, titleAngle=0, titleAlign="left",
                              titleY=-10, titleX=0)),
        color=alt.Color("series:N", title=" ",
                        scale=alt.Scale(domain=series,
                                        range=[BLUE_PALE, BLUE_DEEP]),
                        legend=alt.Legend(orient="bottom", offset=5,
                                          titlePadding=5)),
        order=alt.Order("order:Q", sort="ascending"),
        tooltip=["workshop:N", alt.Tooltip("value:Q", title="value"),
                 alt.Tooltip("series:N", title="color")])
    st.altair_chart(chart.interactive(), use_container_width=True)

    st.markdown("**🧬 Cost × defect rate (bubble = live queue)**")
    trade = pd.DataFrame({"cost_per_pc": cost, "defect_rate": defect,
                          "queue_days": live, "workshop": names})
    # Same spec st.scatter_chart builds, plus a name beside each bubble
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
