"""api/charts.py — dashboard charts rendered server-side with matplotlib.

The SVG charts had no axes; matplotlib gives us real ones for free, in the
same blue palette as the UI. Each function returns PNG bytes.
"""
import io

BLUE_DEEP, BLUE, BLUE_SOFT, BLUE_PALE = "#1971c2", "#339af0", "#74c0fc", "#d0ebff"
INK, MUTED = "#1c2b3a", "#868e96"


def _fig(w, h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    ax.spines[["top", "right"]].set_visible(False)
    return fig, ax, plt


def _png(fig, plt):
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def timeline(points):
    fig, ax, plt = _fig(7.2, 2.6)
    if not points:
        ax.text(0.5, 0.5, "Queue timeline appears after the first commit",
                ha="center", va="center", transform=ax.transAxes, color=MUTED)
        ax.set_xticks([]); ax.set_yticks([])
        return _png(fig, plt)
    shops = sorted({p["workshop"] for p in points})
    palette = [BLUE_DEEP, BLUE, BLUE_SOFT, "#2b8a3e", "#f08c00", "#e8590c", MUTED, "#845ef7"]
    xs = sorted({p["t"] for p in points})
    for i, s in enumerate(shops):
        pts = [p for p in points if p["workshop"] == s]
        ax.step(range(len(pts)), [p["queue"] for p in pts], where="post",
                color=palette[i % len(palette)], lw=2, label=s)
    ax.set_ylabel("queue (days)")
    ax.set_xlabel("commits")
    ax.legend(fontsize=7, frameon=False, ncol=4)
    return _png(fig, plt)


def capacity(rows):
    fig, ax, plt = _fig(7.2, 2.6)
    names = [r["workshop"] for r in rows]
    cur = [r["current"] for r in rows]
    prof = [r["profile"] for r in rows]
    x = range(len(names))
    ax.bar([i - 0.2 for i in x], cur, width=0.4, color=BLUE_DEEP, label="current")
    ax.bar([i + 0.2 for i in x], prof, width=0.4, color=BLUE_PALE, label="profile")
    ax.set_xticks(list(x)); ax.set_xticklabels(names, fontsize=7.5, rotation=20)
    ax.set_ylabel("capacity (pcs/day)")
    ax.legend(fontsize=8, frameon=False)
    return _png(fig, plt)


def lens(candidates, chosen_id, due_slack=None):
    fig, ax, plt = _fig(7.2, 2.6)
    names = [f"{c['name']} ({c['workshop_id']})" for c in candidates]
    vals = [c["est_finish_days"] for c in candidates]
    colors = [BLUE_DEEP if c["workshop_id"] == chosen_id else BLUE_PALE
              for c in candidates]
    ax.bar(names, vals, color=colors, width=0.55)
    if due_slack is not None:
        ax.axhline(due_slack, color="#e03131", ls="--", lw=1.2)
        ax.text(len(names) - 1, due_slack, " due", color="#e03131",
                va="bottom", fontsize=8)
    ax.set_ylabel("expected finish (days)")
    ax.set_xticklabels(names, fontsize=7.5, rotation=20)
    return _png(fig, plt)


def distribution(dist):
    """Behaviour distribution as a horizontal bar chart."""
    fig, ax, plt = _fig(7.2, 2.4)
    if not dist:
        ax.text(0.5, 0.5, "No decisions yet", ha="center", va="center",
                transform=ax.transAxes, color=MUTED)
        ax.set_xticks([]); ax.set_yticks([])
        return _png(fig, plt)
    colors = {"allocate": "#8ce99a", "refuse": "#ffa8a8", "impossible": "#ffd8a8",
              "ask": BLUE_PALE, "answer": "#dee2e6", "no_data": "#dee2e6"}
    labels = list(dist.keys())
    vals = [dist[k] for k in labels]
    ax.barh(labels, vals, color=[colors.get(k, BLUE_SOFT) for k in labels])
    ax.set_xlabel("requests")
    return _png(fig, plt)


def error_types(errors):
    fig, ax, plt = _fig(7.2, 2.4)
    labels = list(errors.keys())
    vals = [errors[k] for k in labels]
    ax.bar(labels, vals, color=["#ffa8a8", "#ffd8a8", "#dee2e6", BLUE_PALE, "#e03131"][:len(labels)])
    ax.set_ylabel("count")
    ax.set_xticklabels(labels, fontsize=8, rotation=15)
    return _png(fig, plt)


def usage_trend(rows):
    fig, ax, plt = _fig(7.2, 2.4)
    if not rows:
        ax.text(0.5, 0.5, "No API usage recorded", ha="center", va="center",
                transform=ax.transAxes, color=MUTED)
        ax.set_xticks([]); ax.set_yticks([])
        return _png(fig, plt)
    days = [r["day"][5:] for r in rows]
    vals = [r["rounds"] for r in rows]
    ax.plot(days, vals, marker="o", color=BLUE_DEEP, lw=2)
    ax.fill_between(days, vals, color=BLUE_PALE, alpha=0.5)
    ax.set_ylabel("LLM rounds")
    ax.set_xticklabels(days, fontsize=8, rotation=20)
    return _png(fig, plt)


def objective_map(bubbles):
    fig, ax, plt = _fig(7.2, 3.0)
    for b in bubbles:
        ax.scatter(b["cost"], b["defect"], s=40 + 160 * b["queue"],
                   color=BLUE_SOFT, alpha=0.7, edgecolors=BLUE_DEEP)
        ax.annotate(b["workshop"], (b["cost"], b["defect"]),
                    xytext=(6, 4), textcoords="offset points", fontsize=7.5)
    ax.set_xlabel("cost ($/pc)")
    ax.set_ylabel("defect rate")
    ax.set_title("bubble size = live queue (days)", fontsize=8, color=MUTED)
    return _png(fig, plt)
