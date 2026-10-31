"""
ui_inbox — the 🗂 Desk tab: paste box, KPI row, case filter and the
per-request cards (understood / candidates / confirm / 4th-option chat).

The confirmation-flow helpers (_replace_item, _log_exchange, _budget_ok,
_norm_msg, render_item_chat) live in app.streamlit_app because the safety
tests exec them straight from that file's AST — so they are imported lazily
inside the functions that need them (a top-level import would be circular).
"""

import streamlit as st

from desk.contracts import Behaviour, Decision
from desk.chat_dump import ENVELOPE, split_chat_dump
from desk.budget import BudgetExceeded
from desk.tools import flag_at_risk
from app.ui_shared import BADGE, NEEDS_HUMAN, _sync_anchor, card


# ---------------- decision rendering (worklist) ----------------

def render_understood(decision):
    """Step 2 — 'Here's what I understood'."""
    p = decision.parsed
    label, color = BADGE[decision.behaviour]
    rows = [f'<div class="field"><b>behaviour</b> '
            f'<span style="background:{color};padding:1px 8px;'
            f'border-radius:8px">{label}</span></div>']
    if p.order_id:
        rows.append(f'<div class="field"><b>order</b> {p.order_id}</div>')
    if p.category or p.pieces:
        what = " ".join(x for x in [p.category, f"{p.pieces} pcs" if p.pieces else None] if x)
        rows.append(f'<div class="field"><b>batch</b> {what}</div>')
    if p.due_date:
        rows.append(f'<div class="field"><b>due</b> {p.due_date}</div>')
    if p.suggested_workshop:
        rows.append(f'<div class="field"><b>suggested</b> {p.suggested_workshop}</div>')
    card("".join(rows))


def _star_on_single(decision, c):
    """The ⭐ goes to the chosen workshop, unless the desk recommends a split
    (IMPOSSIBLE orders), in which case it moves to that split option."""
    return (decision.recommended_split is None and decision.chosen is not None
            and c.workshop_id == decision.chosen.workshop_id)


def render_candidates(decision):
    """Step 3 — candidate cards, chosen one highlighted."""
    if not decision.candidates:
        return
    st.markdown("**🧭 Candidates**")
    for i, c in enumerate(decision.candidates[:3]):
        is_chosen = _star_on_single(decision, c)
        slack = ""
        if decision.parsed.due_date:
            from datetime import date
            slack_days = (date.fromisoformat(decision.parsed.due_date)
                          - date.fromisoformat(c.estimated_finish)).days
            slack = (f"{slack_days} days early" if slack_days >= 0
                     else f"{-slack_days} days late")
        body = (f'<b>{c.name} ({c.workshop_id})</b>'
                + (" ⭐" if is_chosen else "")
                + f'<br>Finish {c.estimated_finish} · {slack}'
                + f'<br>Cost {c.cost:.2f} · Defect {c.defect_risk:.2f}')
        card(body)


def render_confirm(decision, desk):
    """Step 4 — one confirm button per top candidate (the recommendation is
    advisory). The fourth option lives in render_decision, not here, so it
    is available even when there are no candidates (ASK flows)."""
    from desk.desk import ProposalChanged
    from app.streamlit_app import _log_exchange, _replace_item
    if not decision.candidates or decision.parsed.order_id is None:
        return
    st.markdown("**⚙️ Confirm (the recommendation is advisory — you may pick another)**")
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
    st.markdown("**✂️ Split options**")
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


def render_decision(decision, desk):
    """Pre-commit: understood / candidates / confirm buttons, plus the 4th
    option — an expander with the live candidate board and the per-item
    conversation (the agent's reply shows there, first bubble).
    Post-commit: a single line — the confirm UI deletes itself."""
    from app.streamlit_app import render_item_chat
    r = st.session_state.get(f"committed-{id(decision)}")
    if r is not None:
        st.success(f"⚡ Committed {_committed_line(r)}")
        return
    render_understood(decision)
    for note in decision.warnings:
        st.warning(note, icon="⚠️")
    render_candidates(decision)
    render_confirm(decision, desk)
    render_split(decision, desk)
    # the 4th option, available on every uncommitted item (incl. ASK items
    # with no candidates): an expander — st.chat_input/popover cannot hold
    # a working chat input, so the dialog uses a text form
    with st.expander("💬 Other option (tell me)"):
        render_item_chat(decision, desk)


# ---------------- 🗂 inbox worklist ----------------

def _save_thread(decision, desk):
    """Snapshot the agent's current thread as this item's conversation."""
    from app.streamlit_app import _norm_msg
    st.session_state[f"conv-{id(decision)}"] = [_norm_msg(m)
                                                for m in desk.agent.history]


def _row_label(i, item):
    d = item["decision"]
    label, _ = BADGE[d.behaviour]
    what = d.parsed.order_id or item["msg"][:24]
    return f"#{i} · {what} · {label.split()[1]}"


def render_inbox(desk):
    from app.streamlit_app import _budget_ok, _log_exchange
    st.caption("Paste the whole group-chat dump; lines are dispatched one by "
               "one (each stands alone, no shared context).")
    text = st.text_area("Paste group-chat messages", height=120,
                        placeholder="Ravi: ORD-063 — 100 cardigans, make Apr 29.",
                        key="paste_box")
    b_send, b_clear = st.columns([5, 1])
    # Clear empties the paste box only; results and the chat log stay
    b_clear.button("🧹 Clear", use_container_width=True,
                   on_click=lambda: st.session_state.update(paste_box=""))
    if b_send.button("🚀 Dispatch", use_container_width=True, type="primary") and text.strip():
        msgs = split_chat_dump(text.strip())
        if _budget_ok(len(msgs)):
            decisions = []
            for i, msg in enumerate(msgs, 1):
                desk.agent.new_conversation()  # inbox lines are independent
                with st.spinner(f"Dispatching ({i}/{len(msgs)}: {msg[:40]}...)"):
                    st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
                    try:
                        decision = desk.handle_message(msg, requester="dispatcher")
                    except BudgetExceeded:
                        decision = Decision(request_id="", behaviour=Behaviour.ASK,
                            explanation="Request limit reached. Please try again later.")
                    except Exception:
                        decision = Decision(request_id="", behaviour=Behaviour.ASK,
                            explanation="Request failed. Please retry later or check server configuration.")
                    decisions.append({"msg": msg, "decision": decision})
                    _save_thread(decision, desk)   # per-item conversation seed
                    env = ENVELOPE.match(msg)
                    _log_exchange(env.group(3) if env else "chat",
                                  env.group(4) if env else msg,
                                  decision.explanation,
                                  link=f"d{id(decision)}")
            st.session_state.decisions = decisions
            # the sidebar chat log was drawn before this loop ran; rerun so
            # the new exchanges show up now, not after the next click
            st.rerun()

    items = st.session_state.get("decisions", [])
    if not items:
        st.info("Inbox is empty.")
        return

    def case_of(x):
        """The filter a decision lives under (ANSWER is shown with NO DATA)."""
        b = x["decision"].behaviour
        return Behaviour.NO_DATA if b is Behaviour.ANSWER else b

    # items per case still waiting on the dispatcher (committed ones drop out)
    pending = {}
    for x in items:
        if f"committed-{id(x['decision'])}" not in st.session_state:
            pending[case_of(x)] = pending.get(case_of(x), 0) + 1
    to_confirm = pending.get(Behaviour.ALLOCATE, 0)

    # KPI row
    risk = flag_at_risk(desk=desk)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("⚠️ Needs you", sum(1 for x in items if x["decision"].behaviour in NEEDS_HUMAN))
    k2.metric("🟢 To confirm", to_confirm)
    k3.metric("✅ Committed", len({r.order_id for r in desk.audit.load_all()}))
    k4.metric("🕒 Total queue (days)", round(sum(desk.state.queues.values()), 1))
    k5.metric("🔴 At risk", risk["n_at_risk"])
    if risk["n_at_risk"]:
        with st.expander(f"🔴 {risk['n_at_risk']} committed batch(es) "
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
    picked = st.segmented_control(
        "Case", options=FILTERS,
        format_func=lambda b: f"{BADGE[b][0]} ({pending.get(b, 0)})",
        selection_mode="single", default=Behaviour.ALLOCATE)
    shown = [x for x in items if case_of(x) is picked]
    st.markdown(f"**{BADGE[picked][0]} · {len(shown)} request(s)**")
    if not shown:
        st.info("Nothing in this case.")

    # pending items expanded (read before you confirm), committed items
    # collapse to their one-line record
    n = 0
    for item in shown:
        n += 1
        d = item["decision"]
        committed = f"committed-{id(d)}" in st.session_state
        with st.expander(_row_label(n, item), expanded=not committed):
            _sync_anchor(f"d{id(d)}")
            st.caption(item["msg"])
            render_decision(d, desk)
