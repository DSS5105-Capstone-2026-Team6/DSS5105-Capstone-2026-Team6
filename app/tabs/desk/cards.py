"""
tabs.desk.cards — everything one expanded request card renders: understood
line, candidate cards with live queue bars, confirm buttons, the actions
row, split options, and the 4th-option chat entry.

render_decision() is the entry point (called once per worklist row). The
confirmation-flow helpers (_replace_item, _log_exchange, render_item_chat)
live in app.streamlit_app because the safety tests exec them straight from
that file's AST — so they are imported lazily inside the functions that
need them (a top-level import would be circular).
"""

import streamlit as st

from desk.contracts import Behaviour
from app.theme.tokens import BADGE
from app.theme.icons import icon, section
from app.components.cards import card, queue_bar_html
from app.components.ledger_cache import ledger_records


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


def clickable_card(key, body, delay=0.0, chosen=False, label="Confirm"):
    """A card that IS the button: the card html plus a transparent
    st.button stretched over it (CSS in theme.styles, .st-key-pick_*).
    Returns True on click. The hover hint makes the action explicit,
    because one click commits."""
    with st.container(key=f"pick_{key}"):
        card(body + f'<div class="pick-hint">▶ Click to {label[0].lower() + label[1:]}</div>',
             delay=delay, cls="chosen" if chosen else "")
        return st.button(label, key=f"btn-{key}", use_container_width=True)


def render_candidates(decision, desk):
    """Step 3+4 — candidate cards; clicking a card confirms that workshop
    (the recommendation, marked ⭐, is advisory). Compact layout: name + bar
    on top, all numbers on one muted line. The bar shows the workshop's
    CURRENT queue (re-read every rerun) with this order's expected work
    stacked on top."""
    from dataclasses import replace
    from desk.desk import ProposalChanged
    from app.streamlit_app import _log_exchange, _replace_item
    if not decision.candidates:
        return
    can_commit = decision.parsed.order_id is not None
    section("Candidates · live queue"
            + (" · click a card to confirm" if can_commit else ""), "compass")
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
                + (' ⭐ <span class="rec">recommended</span>' if is_chosen else "")
                + queue_bar_html(live[c.workshop_id], added[c.workshop_id], scale)
                + f'<div class="qbar-legend">{meta}</div>')
        if not can_commit:
            card(body, delay=0.06 * i)
            continue
        if clickable_card(f"{id(decision)}-{c.workshop_id}", body,
                          delay=0.06 * i, chosen=is_chosen,
                          label=f"Confirm {c.name} ({c.workshop_id})"):
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
            st.session_state.scroll_from = id(decision)   # jump to the next order
            line = (f"Committed {record.record_id} — "
                    f"{record.order_id} → {record.workshop_id}.")
            _log_exchange("dispatcher", f"(card) {c.name} ({c.workshop_id})",
                          line)
            st.rerun()


def _part_work_days(desk, wid, pieces):
    """Expected work days one split part adds to its workshop's queue —
    the allocator's formula, on the learned capacity when it is active."""
    w = desk.workshops.workshops[wid]
    perf = getattr(desk, "performance", None)
    learned = perf.learned(wid, profile=w) if perf else None
    cap = learned["eff_capacity"] if learned else w.capacity
    return pieces / cap * (1 + 0.5 * w.defect_rate)


def render_split(decision, desk):
    """Step 4b — split options over any number of workshops, ranked by days
    late, each faster than the best single batch. Same card style as the
    candidates: one queue bar per part (live queue + this part's work);
    clicking the card commits every part together (one record each). The
    simulator itself still sends one batch to one workshop."""
    from desk.desk import ProposalChanged
    from app.streamlit_app import _log_exchange, _replace_item
    if not decision.splits or decision.parsed.order_id is None:
        return
    section("Split options · click a card to confirm", "scissors")
    queues = desk.state.queues
    rows = [[(p, queues.get(p["workshop_id"], 0.0),
              _part_work_days(desk, p["workshop_id"], int(p["pieces"])))
             for p in split["parts"]] for split in decision.splits]
    scale = max([q + a for parts in rows for _, q, a in parts] + [0.1])
    for i, split in enumerate(decision.splits):
        parts = " + ".join(f"{p['pieces']} pcs {p['name']} ({p['workshop_id']})"
                           for p in split["parts"])
        late = ("on time" if split["meets_due"]
                else f"{split['days_late']}d late")
        star = i == decision.recommended_split
        bars = "".join(
            f'<div class="split-part"><div class="split-name">{p["pieces"]} pcs · '
            f'{p["name"]} ({p["workshop_id"]})'
            f'<span class="qbar-legend"> · queue {q:.1f}d + {a:.1f}d</span></div>'
            + queue_bar_html(q, a, scale) + '</div>'
            for p, q, a in rows[i])
        body = (f"<b>#{i + 1} · {split['n_shops']} workshops</b>"
                + (' ⭐ <span class="rec">recommended</span>' if star else "")
                + bars
                + f'<div class="qbar-legend">finish {split["earliest_finish"]} ({late})'
                  f' · cost {split["cost"]:.2f} · defect {split["defect_risk"]:.2f}</div>')
        if clickable_card(f"{id(decision)}-split-{i}", body, delay=0.06 * i,
                          chosen=star, label=f"Confirm split #{i + 1}"):
            try:
                records = desk.confirm_split(decision, i, committed_by="dispatcher")
            except ProposalChanged as exc:
                _replace_item(decision, exc.decision, str(exc))
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state[f"committed-{id(decision)}"] = records
            st.session_state.scroll_from = id(decision)   # jump to the next order
            _log_exchange("dispatcher", f"(card) split #{i + 1}: {parts}",
                          "Committed " + _committed_line(records) + ".")
            st.rerun()


def ledger_records_for(desk, order_id):
    """The audit records already committed for order_id (one, or every
    part of a split); [] when the order is still open. Reads go through the
    version-gated cache — with a long worklist this runs once per card."""
    if not order_id:
        return []
    return [r for r in ledger_records(desk) if r.order_id == order_id]


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


def is_skipped(decision):
    """The dispatcher closed this request with Skip (nothing committed)."""
    return f"skipped-{id(decision)}" in st.session_state


def render_skip(decision, help_text):
    """One-tap close for a request that cannot or should not be committed
    (already in the ledger, order not found, refused, ...): no chat round,
    nothing committed; the page moves on to the next open request."""
    from app.streamlit_app import _log_exchange
    if st.button("⏭ Skip", key=f"skip-{id(decision)}", help=help_text):
        st.session_state[f"skipped-{id(decision)}"] = True
        st.session_state.scroll_from = id(decision)   # jump to the next order
        what = decision.parsed.order_id or "request"
        _log_exchange("dispatcher", f"(skip) {what}",
                      f"Skipped {what} — nothing was committed.")
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
    if is_skipped(decision):
        c_note, c_undo = st.columns([4, 1])
        c_note.caption("⏭ Skipped — nothing was committed.")
        if c_undo.button("↩ Undo", key=f"unskip-{id(decision)}",
                         help="Reopen this request"):
            del st.session_state[f"skipped-{id(decision)}"]
            st.rerun()
        return
    render_understood(decision)
    # another card (or an earlier session) already committed this order:
    # say so and hide the confirm/split buttons, which would only be refused
    earlier = ledger_records_for(desk, decision.parsed.order_id)
    if earlier:
        st.info(f"Already committed: {_committed_line(earlier if len(earlier) > 1 else earlier[0])}"
                " — no further commit possible for this order.", icon="✅")
        render_skip(decision, "Duplicate request: close it without committing")
        return
    for note in decision.warnings:
        st.warning(note, icon="⚠️")
    render_candidates(decision, desk)   # cards are the confirm buttons
    render_actions(decision, desk)
    render_split(decision, desk)
    if not (decision.parsed.order_id and decision.candidates):
        # nothing to confirm here (order not found, refused, a question...):
        # close it in one tap instead of typing "skip" into the chat
        render_skip(decision, "Close this request without committing")
    # the 4th option, available on every uncommitted item (incl. ASK items
    # with no candidates): an expander — st.chat_input/popover cannot hold
    # a working chat input, so the dialog uses a text form
    with st.expander("Other option (tell me)"):
        render_item_chat(decision, desk)
