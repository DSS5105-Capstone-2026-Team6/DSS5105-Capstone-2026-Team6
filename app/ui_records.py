"""
ui_records — the 🧾 tab: the audit ledger view + demo reset.
"""

import streamlit as st

from app.ui_shared import card


def render_recent(desk):
    """Step 7 — the record the group chat never had."""
    top_l, top_r = st.columns([3, 1])
    top_l.caption("Allocations and queues are shared across sessions. Duplicate orders are refused. "
                  "Reset archives the demo allocations; API usage limits remain in effect.")
    if top_r.button("↺ Reset demo", use_container_width=True,
                    help="Archive allocations, reset shared queues to the "
                         "queue on April 1, and wipe learned performance "
                         "for all sessions"):
        desk.audit.reset()
        desk.performance.clear()   # learned capacity resets with the world
        for key in list(st.session_state):
            if str(key).startswith(("committed-", "conv-")) or key in {"decisions", "chat_log"}:
                del st.session_state[key]
        st.rerun()

    records = desk.audit.load_all()
    if not records:
        st.info("No committed records yet.")
        return
    for r in reversed(records):
        split = r.evidence.get("split")
        part = f" · split {split['part']}/{split['of']}" if split else ""
        card(f"<b>{r.record_id}</b> · {r.order_id} → {r.workshop_id} "
             f"({r.pieces} pcs{part})<br>"
             f"<span class='muted'>{r.committed_by} · {r.committed_at} · "
             f"queue {r.queue_before} → {r.queue_after} d</span>")
