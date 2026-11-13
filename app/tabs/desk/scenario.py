"""
tabs.desk.scenario — the scenario preview on the Desk tab: what changes if
workshops close on Sundays, transport takes extra days, or capacity gets
noisy (seeded).

compare_sunday() is the pure computation (unit-tested); render_sunday_preview()
is its expander UI above the inbox.
"""

from datetime import date, timedelta
from desk.scenario import finish_production

from desk import config
from desk.allocator import est_finish_days, order_rows, rank_candidates



def compare_sunday(
    order_id, orders, workshops, queues, sunday_closed,
    transport_delay_days=0, perf=None, *, noise_pct=0, seed=5105,
    preview_date=None,
):
    order = orders.by_id(order_id) if order_id else None
    if order is None:
        return {"error": f"unknown order {order_id!r}"}

    order_date = date.fromisoformat(order["order_date"])
    due = date.fromisoformat(order["due_date"])
    start = (
        config.chat_today()
        if preview_date is None
        else max(preview_date, order_date)
    )

    baseline = rank_candidates(
        order_id,
        objective="lateness",
        orders=orders,
        store=workshops,
        queues=queues,
        perf=perf,
        as_of=start,
    )
    if "error" in baseline:
        return baseline

    batch = {"pieces": int(order["pieces"])}
    scenario_rows = []

    for row in baseline["candidates"]:
        workshop = workshops.workshops[row["workshop_id"]]
        baseline_days = est_finish_days(batch, workshop, queues, perf)
        learned = perf.learned(workshop.workshop_id, profile=workshop) if perf else None
        lead = learned["eff_lead_days"] if learned else workshop.lead_days

        # The production calendar covers the queue and this batch's work.
        work_days = baseline_days - lead
        production_finish, pause = finish_production(
            start, 0, work_days, workshop.workshop_id,
            sunday_closed=sunday_closed,
            noise_pct=noise_pct,
            seed=seed,
        )

        scenario_days = production_finish + lead
        total_days = scenario_days + transport_delay_days
        finish = start + timedelta(
            days=round(scenario_days) + transport_delay_days
        )

        scenario_rows.append({
            **row,
            "estimated_finish": finish.isoformat(),
            "est_finish_days": round(total_days, 2),
            "days_late": max(0, (finish - due).days),
            "expected_days_late": round(
                max(0, total_days - (due - start).days), 2
            ),
            "sunday_pause_days": pause,
        })

    return {
        "start_date": start,
        "due_date": due,
        "baseline": baseline["candidates"],
        "scenario": scenario_rows,
    }


def render_sunday_preview(desk):
    import streamlit as st

    with st.container():
        order_id = st.text_input("Order ID", "ORD-063", key="sunday_order")
        order = desk.orders.by_id(order_id) if order_id else None
        if order is None:
            st.warning("Enter a valid order ID, for example ORD-063.")
            return

        order_date = date.fromisoformat(order["order_date"])
        date_options = {
            "Order date": order_date,
            "January 1, 2026": date(2026, 1, 1),
            "April 1, 2026": date(2026, 4, 1),
            "Custom date": None,
        }
        date_choice = st.selectbox(
            "Preview start date",
            list(date_options),
            key="scenario_date_choice",
        )
        preview_date = date_options[date_choice]

        if date_choice == "Custom date":
            preview_date = st.date_input(
                "Pick a date",
                value=order_date,
                min_value=order_date,
                key=f"scenario_custom_date_{order['order_id']}",
            )
            if preview_date is None:
                st.info("Pick a date to calculate ETAs.")
                return

        closed = st.checkbox("Close workshops on Sundays", key="sunday_closed")
        delay = int(st.number_input(
            "Extra transport days", min_value=0, max_value=14, value=0, step=1
        ))
        noise_pct = st.number_input(
            "Capacity noise (%)", min_value=0, max_value=50,
            value=0, step=5, key="scenario_noise_pct",
        )
        seed = st.number_input(
            "Scenario seed", min_value=0, value=5105,
            step=1, key="scenario_capacity_seed",
        )
        objective = st.session_state.get("objective_pref", "hybrid")
        queues = dict(desk.state.queues)

        st.caption(f"Desk date: {config.chat_today()} · Objective: {objective}")
        st.caption(
            "Workshop profiles (learned capacity where active) "
            "and a snapshot of current queues."
        )

        # memoize per (inputs, ledger version): a rerun (e.g. pasting into
        # the inbox) must not re-rank every candidate and re-read the
        # performance table for every workshop over a cross-border link
        cache_key = (order_id.strip().upper(), preview_date, closed, delay,
                     noise_pct, seed, objective, desk.audit.version)
        cached = st.session_state.get("_scenario_cache")
        if cached is not None and cached[0] == cache_key:
            result = cached[1]
        else:
            result = compare_sunday(
                order_id, desk.orders, desk.workshops, queues, closed, delay,
                perf=desk.performance,
                noise_pct=noise_pct,
                seed=seed,
                preview_date=preview_date,
            )
            st.session_state["_scenario_cache"] = (cache_key, result)
        if "error" in result:
            st.warning(result["error"])
            return

        start = result["start_date"]
        due = result["due_date"]
        st.caption(
            f"Order date: {order_date} · Selected date: {preview_date} · "
            f"ETA start: {start} · Due date: {due}"
        )

        if preview_date < order_date:
            st.info(
                f"The order was placed after {preview_date}. "
                f"ETAs start on {start}, the order date."
            )

        days_to_due = (due - start).days
        if days_to_due < 0:
            st.warning(
                f"The deadline had already passed by {-days_to_due} day(s) "
                f"at the preview start."
            )
        elif days_to_due == 0:
            st.warning("The order is due on the preview start date.")
        else:
            st.caption(f"{days_to_due} day(s) from ETA start to the deadline.")
        if not result["baseline"]:
            st.warning("No eligible workshops for this order.")
            return

        baseline_pick = order_rows(result["baseline"], objective)[0]
        scenario_pick = order_rows(result["scenario"], objective)[0]
        if all(row["days_late"] > 0 for row in result["scenario"]):
            st.warning("No eligible single-workshop option meets the due date.")
        st.write(
            f"Baseline pick: {baseline_pick['name']} · "
            f"Scenario pick: {scenario_pick['name']}"
        )

        st.dataframe([
            {
                "Workshop": before["name"],
                "Baseline ETA": before["estimated_finish"],
                "Scenario ETA": after["estimated_finish"],
                "Scenario turnaround (days)": after["est_finish_days"],
                "Sunday pause (days)": after["sunday_pause_days"],
                "Extra transport (days)": delay,
                "Scenario late days": after["days_late"],
            }
            for before, after in zip(result["baseline"], result["scenario"])
        ], hide_index=True)

        st.markdown("**Scenario result**")
        st.write(
            f"For {order_id.strip().upper()}, the {objective} ranking recommends "
            f"{scenario_pick['name']} ({scenario_pick['workshop_id']}). "
            f"Estimated delivery is {scenario_pick['estimated_finish']}, "
            f"with {scenario_pick['days_late']} late day(s), "
            f"estimated cost {scenario_pick['cost']:.2f}, and "
            f"defect risk {scenario_pick['defect_risk']:.1%}."
        )

        ranking_reason = {
            "hybrid": (
                "Hybrid compares delivery first, then favours lower defect "
                "risk within the allowed tolerance."
            ),
            "lateness": (
                "Lateness ranking favours fewer expected late days, "
                "then earlier delivery."
            ),
            "defects": "Defects ranking favours lower estimated defect risk.",
            "cost": "Cost ranking favours the cheapest on-time option when available.",
        }
        st.write(ranking_reason[objective])

        for before, after in zip(result["baseline"], result["scenario"]):
            if before["estimated_finish"] != after["estimated_finish"]:
                st.write(
                    f"- {after['name']}: {before['estimated_finish']} → "
                    f"{after['estimated_finish']}. "
                    f"Sunday pause: {after['sunday_pause_days']} day(s). "
                    f"Extra transport: {delay} day(s)."
                )
