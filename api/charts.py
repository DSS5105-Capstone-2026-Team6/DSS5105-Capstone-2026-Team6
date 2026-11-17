"""api/charts.py — dashboard chart data builders.

The dashboard renders with Plotly in the browser (box-zoom rescales both
axes, pan, hover, double-click reset — no server round-trip). These
functions only shape the data each trace needs; no matplotlib, no PNGs.
"""

BEHAVIOUR_COLORS = {"allocate": "#8ce99a", "refuse": "#ffa8a8",
                    "impossible": "#ffd8a8", "ask": "#d0ebff",
                    "answer": "#dee2e6", "no_data": "#dee2e6"}


def timeline(points):
    """[{t, queue, workshop}] -> per-workshop step series."""
    shops = sorted({p["workshop"] for p in points})
    series = []
    for s in shops:
        pts = [p for p in points if p["workshop"] == s]
        series.append({"workshop": s,
                       "x": list(range(len(pts))),
                       "y": [p["queue"] for p in pts]})
    return {"series": series}


def capacity(rows):
    """[{workshop, profile, current}] -> grouped bars."""
    return {"workshops": [r["workshop"] for r in rows],
            "profile": [r["profile"] for r in rows],
            "current": [r["current"] for r in rows]}


def lens(candidates, chosen_id, due_slack=None):
    return {"names": [f"{c['name']} ({c['workshop_id']})" for c in candidates],
            "finish": [c["est_finish_days"] for c in candidates],
            "chosen": chosen_id,
            "ids": [c["workshop_id"] for c in candidates],
            "due_slack": due_slack}


def distribution(dist):
    """{behaviour: n} -> horizontal bars, behaviour colours."""
    labels = list(dist.keys())
    return {"labels": labels,
            "values": [dist[k] for k in labels],
            "colors": [BEHAVIOUR_COLORS.get(k, "#74c0fc") for k in labels]}


def error_types(errors):
    labels = list(errors.keys())
    palette = ["#ffa8a8", "#ffd8a8", "#dee2e6", "#d0ebff", "#e03131"]
    return {"labels": labels,
            "values": [errors[k] for k in labels],
            "colors": palette[:len(labels)]}


def usage_trend(rows):
    return {"days": [r["day"][5:] for r in rows],
            "rounds": [r["rounds"] for r in rows]}


def objective_map(bubbles):
    return {"workshops": [b["workshop"] for b in bubbles],
            "cost": [b["cost"] for b in bubbles],
            "defect": [b["defect"] for b in bubbles],
            "queue": [b["queue"] for b in bubbles]}
