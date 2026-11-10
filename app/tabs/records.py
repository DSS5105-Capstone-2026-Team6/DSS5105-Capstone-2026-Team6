"""
tabs.records — the Records tab: the audit ledger view + demo reset.
"""

import streamlit as st

from app.components.cards import card
from app.components.ledger_cache import ledger_records


def _clear_demo_state():
    """Wipe this session's cards/conversations so a storage switch starts
    from a clean desk (same key set as Reset demo)."""
    for key in list(st.session_state):
        if str(key).startswith(("committed-", "conv-")) or key in {"decisions", "chat_log"}:
            del st.session_state[key]


def render_recent(desk):
    """Step 7 — the record the group chat never had."""
    top_l, top_r = st.columns([3, 1])
    top_l.caption("Allocations and queues are shared across sessions. Duplicate orders are refused. "
                  "Reset archives the demo allocations; API usage limits remain in effect.")
    if top_r.button("Reset demo", use_container_width=True,
                    help="Archive allocations, reset shared queues to the "
                         "queue on April 1, and wipe learned performance "
                         "for all sessions"):
        desk.audit.reset()
        desk.performance.clear()   # learned capacity resets with the world
        _clear_demo_state()
        st.rerun()

    # ---- shared-DB connection toggle (default: local sandbox) ----
    if st.session_state.get("share_db"):
        st.success("Connected to the shared database — reads and writes are "
                   "shared with the Telegram bot.", icon="🔗")
        if st.button("Disconnect (back to local sandbox)",
                     key="db_disconnect", use_container_width=True):
            _clear_demo_state()
            st.session_state.share_db = False
            st.session_state.desk = None      # rebuild in sandbox mode
            st.session_state.pop("_local_store", None)
            st.rerun()
    else:
        st.caption("Local sandbox: this session never touches the shared "
                   "database — fast for debugging and tests.")
        if st.button("🔗 Reset & connect to shared DB", key="db_connect",
                     use_container_width=True,
                     help="Clear this session's demo state and rebuild the "
                          "desk on the shared database (the same one the "
                          "Telegram bot uses)"):
            _clear_demo_state()
            st.session_state.share_db = True
            st.session_state.desk = None      # rebuild on the shared DB
            st.rerun()

    records = ledger_records(desk)   # version-gated cache; reset bumps the version
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
