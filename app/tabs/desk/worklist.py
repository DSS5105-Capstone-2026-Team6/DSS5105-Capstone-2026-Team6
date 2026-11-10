"""
tabs.desk.worklist — the Desk tab's worklist: KPI row, behaviour filter,
and one expander per request.

Card rendering lives in cards.py (render_decision). The dispatch loop and
the intake live in tabs/desk/__init__.py and intake.py.
"""

import streamlit as st

from desk.contracts import Behaviour
from desk.tools import flag_at_risk
from app.theme.tokens import BADGE, NEEDS_HUMAN
from app.theme.motion import _sync_anchor, scroll_to_anchor
from app.tabs.desk.cards import render_decision
from app.components.ledger_cache import ledger_records


def _row_label(i, item):
    d = item["decision"]
    label, _ = BADGE[d.behaviour]
    what = d.parsed.order_id or item["msg"][:24]
    return f"#{i} · {what} · {label}"


def _refresh_stale(items, desk, is_done):
    """Re-rank open proposals whose state_version is behind the ledger
    (deterministic tools only, no LLM call)."""
    version = desk.audit.version
    for item in items:
        old = item["decision"]
        if (is_done(old) or not old.candidates or old.parsed.order_id is None
                or old.state_version in (None, version)):
            continue
        fresh = desk.refresh(old)
        same = (fresh.chosen and old.chosen
                and fresh.chosen.workshop_id == old.chosen.workshop_id)
        if same:
            # same recommendation: keep the model's explanation, flag the update
            fresh.explanation = old.explanation
            note = "Queues changed after another commit; numbers updated to the live queues."
            fresh.warnings = [*old.warnings] + ([note] if note not in old.warnings else [])
        item["decision"] = fresh
        # carry the card's per-item chat over to the new object
        conv = st.session_state.pop(f"conv-{id(old)}", None)
        if conv is not None:
            st.session_state[f"conv-{id(fresh)}"] = conv


def next_open_item(shown, src_id, is_done):
    """The item to scroll to after committing decision `src_id`: the
    nearest uncommitted one below it, else the nearest uncommitted one
    above it, else None."""
    ids = [id(x["decision"]) for x in shown]
    i = ids.index(src_id) if src_id in ids else -1
    below = shown[i + 1:]
    above = shown[:i][::-1] if i >= 0 else []
    return next((x for x in below + above if not is_done(x["decision"])), None)


def render_worklist(desk, items):
    """KPI row + case filter + the per-request expanders. Committed items
    collapse to their one-line record; pending ones stay expanded (read
    before you confirm)."""
    def case_of(x):
        """The filter a decision lives under (ANSWER is shown with NO DATA)."""
        b = x["decision"].behaviour
        return Behaviour.NO_DATA if b is Behaviour.ANSWER else b

    # items per case still waiting on the dispatcher (committed ones drop out)
    # an order committed on another card (or earlier) counts as done too
    records = ledger_records(desk)   # version-gated: one round-trip per rerun
    done_orders = {r.order_id for r in records}

    def is_done(d):
        return (f"committed-{id(d)}" in st.session_state
                or (d.parsed.order_id is not None and d.parsed.order_id in done_orders))

    # every commit bumps the ledger version, which makes every OTHER open
    # proposal stale: its first Confirm click used to be spent on a silent
    # refresh (ProposalChanged), so each order needed two clicks. Refresh
    # stale open cards here instead, before they are drawn, so the numbers
    # on screen are live and one click commits.
    _refresh_stale(items, desk, is_done)

    pending = {}
    for x in items:
        if not is_done(x["decision"]):
            pending[case_of(x)] = pending.get(case_of(x), 0) + 1
    to_confirm = pending.get(Behaviour.ALLOCATE, 0)

    # KPI row + case filter + worklist share one container, so the five KPI
    # cards and the five behaviour buttons line up column for column
    with st.container(key="worklist", width=740):
        risk = flag_at_risk(desk=desk)
        with st.container(key="kpi_row"):
            k1, k2, k3, k4, k5 = st.columns(5)
            with k1, st.container(key="kpi_needs"):
                st.metric("Needs you", sum(1 for x in items if x["decision"].behaviour in NEEDS_HUMAN))
            with k2, st.container(key="kpi_confirm"):
                st.metric("To confirm", to_confirm)
            with k3, st.container(key="kpi_committed"):
                st.metric("Committed", len({r.order_id for r in records}))
            with k4, st.container(key="kpi_queue"):
                st.metric("Total queue (days)", round(sum(desk.state.queues.values()), 1))
            with k5, st.container(key="kpi_risk"):
                st.metric("At risk", risk["n_at_risk"])
        if risk["n_at_risk"]:
            with st.expander(f"At risk: {risk['n_at_risk']} committed batch(es) "
                             "projected to miss the due date", expanded=True):
                for r in risk["at_risk"]:
                    st.warning(
                        f"**{r['order_id']}** @ {r['workshop_name']} — due "
                        f"{r['due_date']}, projected {r['projected_finish']} "
                        f"(+{r['projected_days_late']}d late). Options: "
                        + " / ".join(risk["options"]))
                st.caption("flag_at_risk is read-only; reassignment still goes "
                           "through the normal human confirmation flow.")

        # one tap = one behaviour: the five cases never stack on the page
        FILTERS = [Behaviour.ALLOCATE, Behaviour.REFUSE, Behaviour.IMPOSSIBLE,
                   Behaviour.ASK, Behaviour.NO_DATA]
        with st.container(key="case_filter"):
            current = st.session_state.get("case_pick", Behaviour.ALLOCATE)
            cols = st.columns(5)
            picked = current
            for col, b in zip(cols, FILTERS):
                label = f"{BADGE[b][0]} ({pending.get(b, 0)})"
                with col, st.container(key=f"case-{b.value}"):
                    if st.button(label, key=f"casebtn-{b.value}",
                                 use_container_width=True,
                                 type="primary" if b is current else "secondary"):
                        picked = b
            if picked is not current:
                st.session_state.case_pick = picked
                st.rerun()
        shown = [x for x in items if case_of(x) is picked]
        st.markdown(f"**{BADGE[picked][0]} · {len(shown)} request(s)**")
        if not shown:
            st.info("Nothing in this case.")

        # batch confirm: every open ALLOCATE card, one audited transaction
        # each — the human spends one click instead of N
        open_alloc = [x["decision"] for x in shown
                      if picked is Behaviour.ALLOCATE
                      and x["decision"].candidates and x["decision"].chosen]
        if len(open_alloc) > 1:
            if st.button(f"✅ Confirm all open ({len(open_alloc)})",
                         key="confirm_all", type="primary",
                         help="Commit the recommended workshop for every open "
                              "ALLOCATE card; per-order checks still apply"):
                from app.streamlit_app import _log_exchange
                results, failures = desk.confirm_all(
                    open_alloc, committed_by="dispatcher")
                for d, record in results:
                    st.session_state[f"committed-{id(d)}"] = record
                    _log_exchange("dispatcher", f"(confirm all) {d.parsed.order_id}",
                                  f"Committed {record.record_id} — "
                                  f"{record.order_id} → {record.workshop_id}.")
                for oid, why in failures:
                    st.warning(f"Not committed: {oid} — {why}", icon="⚠️")
                st.rerun()

        # pending items expanded (read before you confirm), committed items
        # collapse to their one-line record
        n = 0
        for item in shown:
            n += 1
            d = item["decision"]
            committed = is_done(d)
            with st.expander(_row_label(n, item), expanded=not committed):
                _sync_anchor(f"d{id(d)}")
                st.caption(item["msg"])
                render_decision(d, desk)

        # after a commit, bring the next open request to the top of the page
        # (cards / item chat set scroll_from to the committed decision):
        # the nearest open one BELOW first; if none is left below, the
        # nearest open one ABOVE (orders the user skipped for later)
        src_id = st.session_state.pop("scroll_from", None)
        if src_id is not None:
            nxt = next_open_item(shown, src_id, is_done)
            if nxt is not None:
                scroll_to_anchor(f"d{id(nxt['decision'])}")
