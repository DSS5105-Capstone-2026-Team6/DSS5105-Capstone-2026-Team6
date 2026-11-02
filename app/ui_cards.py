"""
ui_cards — everything one expanded request card renders: understood line,
candidate cards with live queue bars, confirm buttons, the actions row,
split options, and the 4th-option chat entry.

render_decision() is the entry point (called once per worklist row). The
confirmation-flow helpers (_replace_item, _log_exchange, render_item_chat)
live in app.streamlit_app because the safety tests exec them straight from
that file's AST — so they are imported lazily inside the functions that
need them (a top-level import would be circular).
"""

import streamlit as st

from desk.contracts import Behaviour
from app.ui_shared import (BADGE, card, icon, queue_bar_html, section)


def render_understood(decision):
    """Step 2 — 'Here's what I understood', one compact line."""
    p = decision.parsed
    label, color = BADGE[decision.behaviour]
    parts = [f'<span style="background:{color};padding:1px 8px;'
             f'border-radius:8px">{label}</span>']
    if p.order_id:
        parts.append(f"<b>{p.order_id}</b>")
    if p.category or p.pieces:
        parts.append(" ".join(x for x in [p.category,
                     f"{p.pieces} pcs" if p.pieces else None] if x))
    if p.due_date:
        parts.append(f"due {p.due_date}")
    if p.suggested_workshop:
        parts.append(f"suggested {p.suggested_workshop}")
    card('<div class="one-line">' + " · ".join(parts) + "</div>")


def _star_on_single(decision, c):
    """The ⭐ goes to the chosen workshop, unless the desk recommends a split
    (IMPOSSIBLE orders), in which case it moves to that split option."""
    return (decision.recommended_split is None and decision.chosen is not None
            and c.workshop_id == decision.chosen.workshop_id)


def render_candidates(decision, desk):
    """Step 3 — candidate cards, chosen one highlighted. Compact two-line
    layout: name + bar on top, all the numbers on one muted line. The bar
    shows the workshop's CURRENT queue (re-read every rerun) with this
    order's expected work stacked on top."""
    if not decision.candidates:
        return
    section("Candidates · live queue", "compass")
    shown = decision.candidates[:3]
    live = {c.workshop_id: desk.state.queues.get(c.workshop_id, 0.0)
            for c in shown}
    added = {c.workshop_id: float(c.components.get("work_days_expected", 0.0))
             for c in shown}
    scale = max([live[c.workshop_id] + added[c.workshop_id] for c in shown]
                + [0.1])
    for i, c in enumerate(shown):
        is_chosen = _star_on_single(decision, c)
        meta = f"queue {live[c.workshop_id]:.1f}d"
        if added[c.workshop_id]:
            meta += f" + {added[c.workshop_id]:.1f}d"
        if decision.parsed.due_date:
            from datetime import date
            slack_days = (date.fromisoformat(decision.parsed.due_date)
                          - date.fromisoformat(c.estimated_finish)).days
            slack = (f"{slack_days}d early" if slack_days >= 0
                     else f"{-slack_days}d late")
            meta += (f" · finish {c.estimated_finish} ({slack})")
        else:
            meta += f" · finish {c.estimated_finish}"
        meta += f" · cost {c.cost:.2f} · defect {c.defect_risk:.2f}"
        body = (f'<b>{c.name} ({c.workshop_id})</b>'
                + (" ⭐" if is_chosen else "")
                + queue_bar_html(live[c.workshop_id], added[c.workshop_id], scale)
                + f'<div class="qbar-legend">{meta}</div>')
        card(body, delay=0.06 * i)


def render_confirm(decision, desk):
    """Step 4 — one confirm button per top candidate (the recommendation is
    advisory). The fourth option lives in render_decision, not here, so it
    is available even when there are no candidates (ASK flows)."""
    from desk.desk import ProposalChanged
    from app.streamlit_app import _log_exchange, _replace_item
    if not decision.candidates or decision.parsed.order_id is None:
        return
    section("Confirm · the recommendation is advisory", "sliders")
    from dataclasses import replace
    for c in decision.candidates[:3]:
        is_chosen = _star_on_single(decision, c)
        label = f"▶ Confirm {c.name} ({c.workshop_id})" + (" ⭐ recommended" if is_chosen else "")
        if st.button(label, use_container_width=True,
                     key=f"btn-{id(decision)}-{c.workshop_id}"):
            try:
                record = desk.confirm(replace(decision, chosen=c),
                                      committed_by="dispatcher")
            except ProposalChanged as exc:
                _replace_item(decision, exc.decision, str(exc))
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state[f"committed-{id(decision)}"] = record
            line = (f"Committed {record.record_id} — "
                    f"{record.order_id} → {record.workshop_id}.")
            _log_exchange("dispatcher", f"(button) {c.name} ({c.workshop_id})",
                          line)
            st.rerun()


def render_split(decision, desk):
    """Step 4b — split options over any number of workshops, ranked by days
    late, each faster than the best single batch. All parts of the chosen
    option commit together (one record each); the simulator itself still
    sends one batch to one workshop."""
    from desk.desk import ProposalChanged
    from app.streamlit_app import _log_exchange, _replace_item
    if not decision.splits or decision.parsed.order_id is None:
        return
    section("Split options", "scissors")
    for i, split in enumerate(decision.splits):
        parts = " + ".join(f"{p['pieces']} pcs {p['name']} ({p['workshop_id']})"
                           for p in split["parts"])
        late = ("on time" if split["meets_due"]
                else f"{split['days_late']} days late")
        star = i == decision.recommended_split
        card(f"<b>#{i + 1} · {split['n_shops']} workshops</b>"
             + (" ⭐" if star else "") + f"<br>{parts}"
             f"<br>Finish {split['earliest_finish']} · {late}"
             f" · Cost {split['cost']:.2f} · Defect {split['defect_risk']:.2f}")
        if st.button(f"▶ Confirm split #{i + 1}" + (" ⭐ recommended" if star else ""),
                     use_container_width=True,
                     key=f"btn-{id(decision)}-split-{i}"):
            try:
                records = desk.confirm_split(decision, i, committed_by="dispatcher")
            except ProposalChanged as exc:
                _replace_item(decision, exc.decision, str(exc))
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state[f"committed-{id(decision)}"] = records
            _log_exchange("dispatcher", f"(button) split #{i + 1}: {parts}",
                          "Committed " + _committed_line(records) + ".")
            st.rerun()


def _committed_line(records):
    """'A-0003 — ORD-029 → W2 (549 pcs) + W6 (951 pcs)' for a split, the
    usual 'A-0001 — ORD-041 → W6' for one record."""
    if not isinstance(records, list):
        return f"{records.record_id} — {records.order_id} → {records.workshop_id}"
    ids = ", ".join(r.record_id for r in records)
    shops = " + ".join(f"{r.workshop_id} ({r.pieces} pcs)" for r in records)
    return f"{ids} — {records[0].order_id} → {shops}"


def render_actions(decision, desk):
    """Fine-grained per-card controls: re-rank (live queues, objective from
    the right-side panel) or dismiss the request — one tap, no chat round."""
    from dataclasses import replace
    from app.streamlit_app import _log_exchange, _replace_item
    if not decision.parsed.order_id or not decision.candidates:
        return
    pref = st.session_state.get("objective_pref", "hybrid")
    c_note, c_refresh, c_dismiss = st.columns([3, 1, 1])
    note = f"objective: {decision.objective}"
    if pref != decision.objective:
        note += f" → {pref} on re-rank"
    c_note.caption(note)
    if c_refresh.button("🔄 Re-rank", key=f"refresh-{id(decision)}",
                        help="Rank again against the live queues, with the "
                             "objective from the right panel"):
        fresh = desk.refresh(replace(decision, objective=pref))
        _replace_item(decision, fresh, f"Re-ranked by {pref}, live queues.")
        _log_exchange("dispatcher", f"(re-rank) {pref}",
                      f"Re-ranked {decision.parsed.order_id} by {pref}.")
        st.rerun()
    if c_dismiss.button("🗑 Dismiss", key=f"dismiss-{id(decision)}",
                        help="Drop this request from the worklist"):
        items = st.session_state.get("decisions", [])
        st.session_state.decisions = [x for x in items
                                      if x["decision"] is not decision]
        st.rerun()


def render_decision(decision, desk):
    """Pre-commit: understood / candidates / confirm buttons, actions row,
    split options, plus the 4th option — an expander with the live
    candidate board and the per-item conversation.
    Post-commit: a single line — the confirm UI deletes itself."""
    from app.streamlit_app import render_item_chat
    r = st.session_state.get(f"committed-{id(decision)}")
    if r is not None:
        st.success(f"Committed {_committed_line(r)}")
        return
    render_understood(decision)
    for note in decision.warnings:
        st.warning(note, icon="⚠️")
    render_candidates(decision, desk)
    render_confirm(decision, desk)
    render_actions(decision, desk)
    render_split(decision, desk)
    # the 4th option, available on every uncommitted item (incl. ASK items
    # with no candidates): an expander — st.chat_input/popover cannot hold
    # a working chat input, so the dialog uses a text form
    with st.expander("Other option (tell me)"):
        render_item_chat(decision, desk)
