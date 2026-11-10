"""
components.ledger_cache — version-gated memo for audit ledger reads.

Every commit bumps the ledger version (audit.reset bumps it too), so a
cached copy is valid exactly while the version matches: each call costs one
small version query, and the full table is re-read only after an actual
write. This collapses the per-rerun pile-up of load_all() calls (KPI row,
done-checks, one lookup per card) into one cheap round-trip.
"""

import streamlit as st


def ledger_records(desk):
    """desk.audit.load_all() memoized on the ledger version. Audits without a
    version property (lightweight fakes in tests) bypass the cache."""
    version = getattr(desk.audit, "version", None)
    if version is None:
        return desk.audit.load_all()
    cache = st.session_state.get("_ledger_cache")
    if cache is not None and cache[0] == version:
        return cache[1]
    records = desk.audit.load_all()
    st.session_state["_ledger_cache"] = (version, records)
    return records
