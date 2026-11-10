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
