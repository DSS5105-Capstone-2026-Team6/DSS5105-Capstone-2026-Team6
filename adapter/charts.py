"""adapter/charts.py — queue chart as a PNG for Telegram (send_photo).

Pure function (queues dict -> PNG bytes) so the tests never touch Telegram.
matplotlib runs headless (Agg); it is a bot-only dependency
(adapter/requirements.txt), the web UI does not need it here.
"""

import io


def queue_chart_png(queues, workshops):
    """Bar chart of live queues, one bar per workshop. queues: {wid: days},
    workshops: {wid: workshop with .name}. Returns PNG bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    wids = sorted(queues)
    names = [workshops[w].name if w in workshops else w for w in wids]
    days = [queues[w] for w in wids]

    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    bars = ax.bar(names, days, color="#339af0", width=0.55)
    ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=8)
    ax.set_ylabel("queue (days)")
    ax.set_ylim(0, max(days + [1]) * 1.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=8, rotation=20)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def queue_text(queues, workshops):
    """The same live queues as plain text: instant, and needs no
    matplotlib, so /queue can always answer even when drawing fails."""
    total = sum(queues.values())
    lines = [f"Live queues · total {total:.1f} days"]
    for w in sorted(queues):
        name = workshops[w].name if w in workshops else w
        lines.append(f"{w} {name}: {queues[w]:.1f} d")
    return "\n".join(lines)


def try_queue_chart(queues, workshops):
    """The chart as PNG bytes, or None if it cannot be drawn here (for
    example matplotlib missing on the host). The error goes to the log."""
    try:
        return queue_chart_png(queues, workshops)
    except Exception:
        import traceback
        traceback.print_exc()
        return None
