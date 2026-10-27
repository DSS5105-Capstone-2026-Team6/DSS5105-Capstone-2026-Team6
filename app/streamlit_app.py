"""
streamlit_app — the dispatcher's desk UI.

The only bridge to the backend is the DispatchDesk facade: handle_message()
turns one chat line into a Decision, confirm() commits it and writes the
audit record. This file renders Decisions and captures taps; it holds no
business logic.

Layout: tab 🗂 desk = worklist (left) + chat log (right). Every handled
message lands in the chat log; the worklist holds the actionable part
(candidates, confirm buttons) and collapses to a one-liner once committed.

Run from the project root:

    uv run streamlit run app/streamlit_app.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from desk.contracts import Behaviour, to_dict
from desk.desk import DispatchDesk
from eval.run_eval import ENVELOPE

# behaviour badge chips: text + tint. Semantics come first (green/red/
# orange/blue); everything else in the UI stays in the light-blue family.
BADGE = {
    Behaviour.ALLOCATE: ("🟢 ALLOCATE", "#d3f9d8"),
    Behaviour.REFUSE: ("🔴 REFUSE", "#ffe3e3"),
    Behaviour.IMPOSSIBLE: ("🟠 IMPOSSIBLE", "#ffe8cc"),
    Behaviour.ASK: ("🔵 ASK", "#d0ebff"),
    Behaviour.ANSWER: ("⚪ ANSWER", "#e9ecef"),
    Behaviour.NO_DATA: ("⚪ NO DATA", "#e9ecef"),
}

# accent palette — light blue family
BLUE_DEEP = "#1971c2"     # primary actions / live series
BLUE = "#339af0"          # chosen highlight
BLUE_SOFT = "#74c0fc"     # chart points
BLUE_PALE = "#d0ebff"     # snapshot series / chips

# inbox buckets: which behaviour needs the human first
NEEDS_HUMAN = {Behaviour.ASK, Behaviour.REFUSE, Behaviour.IMPOSSIBLE,
               Behaviour.NO_DATA}

CSS = """
<style>
.block-container {
    max-width: 1200px;     /* ~2/3 wider than Streamlit's centered 730px */
    margin: auto;
}
.card {
    border: 1px solid #dee2e6; border-radius: 12px;
    padding: 12px 14px; margin: 8px 0; background: #fff;
}
.card.chosen { border: 2px solid #339af0; background: #f1f8fe; }
.muted { color: #868e96; font-size: 0.85em; }
.field { margin: 2px 0; }
.field b { display: inline-block; min-width: 7.5em; }
h1 { font-size: 1.4rem !important; }
</style>
"""


def get_desk():
    """One DispatchDesk per session, so chat-side queues survive reruns.
    The sidebar picks the provider/model; when the pick changes the desk is
    rebuilt (session state keyed on the choice).
    API key: locally from .env (load_api_key); on Streamlit Community Cloud
    from st.secrets, mirrored into os.environ. Locally there is no
    secrets.toml, and merely touching st.secrets raises — hence the guard.
    Hot-reload guard: a desk created before a code update may lack newer
    agent methods; rebuild it rather than crash."""
    from desk.config import DEFAULT_PROVIDER, PROVIDERS
    with st.sidebar:
        provider = st.selectbox(
            "Provider", options=list(PROVIDERS),
            format_func=lambda k: PROVIDERS[k]["label"],
            key="provider_sel")
        model = st.selectbox("Model", options=PROVIDERS[provider]["models"],
                             key="model_sel")
    choice = (provider, model)
    desk = st.session_state.get("desk")
    if desk is not None and (not hasattr(desk.agent, "new_conversation")
                             or st.session_state.get("desk_choice") != choice):
        desk = None
    if desk is None:
        try:
            try:
                secrets = dict(st.secrets)
            except Exception:
                secrets = {}
            key_vars = {v for spec in PROVIDERS.values()
                        for v in spec["key_vars"]}
            key_vars |= {"OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                         "ANTHROPIC_API_KEY"}
            for var in key_vars:
                if secrets.get(var) and not os.environ.get(var):
                    os.environ[var] = secrets[var]
            desk = DispatchDesk(provider=provider, model=model)
            st.session_state.desk = desk
            st.session_state.desk_choice = choice
        except Exception as exc:  # missing API key, unreadable data...
            st.error(f"Backend failed to start: {exc}")
            st.stop()
    return desk


def card(html):
    st.markdown(f'<div class="card">{html}</div>', unsafe_allow_html=True)


def split_chat_dump(text):
    """Split a pasted group-chat dump into single messages. A line matching
    the inbox envelope (R23 [08:29] Priya: ...) starts a new message;
    continuation lines belong to the previous one; # comments and blank
    lines are skipped. One message -> [text]."""
    msgs, current = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ENVELOPE.match(stripped):
            if current:
                msgs.append(current)
            current = stripped
        elif current is None:
            current = stripped
        else:
            current += " " + stripped
    if current:
        msgs.append(current)
    return msgs or [text]


# ---------------- chat log (right rail) ----------------

def _log_exchange(speaker, text, decision):
    """Append one customer/agent exchange to the persistent chat log."""
    st.session_state.setdefault("chat_log", []).append(
        {"speaker": speaker, "text": text, "reply": decision.explanation,
         "behaviour": BADGE[decision.behaviour][0]})


def render_chat_log(desk):
    """The right-hand rail: every message the desk has handled, in order.
    This is the record of what was said — actions live in the worklist."""
    st.markdown("**💬 Chat log**")
    top_l, top_r = st.columns([3, 1])
    top_l.caption(f"{len(st.session_state.get('chat_log', []))} messages")
    if top_r.button("🔄 New chat", use_container_width=True,
                    help="Start a fresh conversation context (the log stays)"):
        desk.agent.new_conversation()

    with st.container(height=520, border=False):
        for turn in st.session_state.get("chat_log", []):
            with st.chat_message("user", avatar="🧑‍🔧"):
                st.write(f"**{turn['speaker']}:** {turn['text']}")
            with st.chat_message("assistant", avatar="🤖"):
                st.write(turn["reply"] if turn["reply"] else "(no reply)")

    queued = st.session_state.pop("queued_input", None)
    prompt = st.chat_input("Follow up on the last request...") or queued
    if prompt and _budget_ok():
        st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
        with st.spinner("Working..."):
            decision = desk.handle_message(prompt, requester="dispatcher")
        _log_exchange("dispatcher", prompt, decision)
        st.rerun()


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


def render_candidates(decision):
    """Step 3 — candidate cards, chosen one highlighted."""
    if not decision.candidates:
        return
    st.markdown("**🧭 Candidates**")
    for i, c in enumerate(decision.candidates[:3]):
        is_chosen = decision.chosen and c.workshop_id == decision.chosen.workshop_id
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
    """Step 4 — the system recommends (⭐), the human decides: every candidate
    gets its own confirm button, not just the top pick. Once committed the
    whole confirm section is gone: rerun lands in the committed branch of
    render_decision, which shows a single line."""
    if not decision.candidates or decision.parsed.order_id is None:
        return
    st.markdown("**⚙️ Confirm (the recommendation is advisory — you may pick another)**")
    from dataclasses import replace
    for c in decision.candidates[:3]:
        is_chosen = decision.chosen and c.workshop_id == decision.chosen.workshop_id
        label = f"▶ Confirm {c.name} ({c.workshop_id})" + (" ⭐ recommended" if is_chosen else "")
        if st.button(label, use_container_width=True,
                     key=f"btn-{id(decision)}-{c.workshop_id}"):
            try:
                record = desk.confirm(replace(decision, chosen=c),
                                      committed_by="dispatcher")
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state[f"committed-{id(decision)}"] = record
            st.rerun()


def render_reply(decision):
    """Step 5 — ready-to-paste group-chat reply (st.code has a copy button)."""
    if not decision.explanation:
        return
    st.markdown("**📤 Copyable reply**")
    st.code(decision.explanation, language=None)


def _queue_input(text):
    """Tappable option -> put the order id into the chat box on next rerun."""
    st.session_state.queued_input = text


def render_options(decision):
    """ASK decisions carry tappable choices (journey step 6): one tap
    answers the clarifying question instead of typing."""
    if not decision.options:
        return
    st.markdown("**⌨️ Tap to reply**")
    for opt in decision.options:
        st.button(f"▶ {opt}", use_container_width=True,
                  key=f"opt-{id(decision)}-{opt}",
                  on_click=_queue_input, args=(opt,))


def render_decision(decision, desk):
    """Pre-commit: full conversation (understood / candidates / confirm /
    options / reply), expanded so the human reads it BEFORE deciding.
    Post-commit: a single line — the confirm UI deletes itself."""
    r = st.session_state.get(f"committed-{id(decision)}")
    if r is not None:
        st.success(f"⚡ Committed {r.record_id} — {r.order_id} → {r.workshop_id}")
        return
    render_understood(decision)
    render_candidates(decision)
    render_confirm(decision, desk)
    render_options(decision)
    render_reply(decision)


# ---------------- 🗂 inbox worklist ----------------

def _budget_ok(extra=1):
    """Per-session request cap (Risk 6): the hosted demo shares one key."""
    n = st.session_state.get("n_sent", 0)
    if n + extra > 40:
        st.warning("Session request cap reached (40). Please reopen the page.")
        return False
    return True


def _row_label(i, item):
    d = item["decision"]
    label, _ = BADGE[d.behaviour]
    what = d.parsed.order_id or item["msg"][:24]
    return f"#{i} · {what} · {label.split()[1]}"


def render_inbox(desk):
    st.caption("Paste the whole group-chat dump; lines are dispatched one by "
               "one (each stands alone, no shared context).")
    text = st.text_area("Paste group-chat messages", height=120,
                        placeholder="Ravi: ORD-063 — 100 cardigans, make Apr 29.")
    if st.button("🚀 Dispatch", use_container_width=True, type="primary") and text.strip():
        msgs = split_chat_dump(text.strip())
        if _budget_ok(len(msgs)):
            decisions = []
            for i, msg in enumerate(msgs, 1):
                desk.agent.new_conversation()  # inbox lines are independent
                with st.spinner(f"Dispatching ({i}/{len(msgs)}: {msg[:40]}...)"):
                    decision = desk.handle_message(msg, requester="dispatcher")
                    decisions.append({"msg": msg, "decision": decision})
                    _log_exchange(ENVELOPE.match(msg).group(3) if ENVELOPE.match(msg) else "chat",
                                  ENVELOPE.match(msg).group(4) if ENVELOPE.match(msg) else msg,
                                  decision)
            st.session_state.n_sent = st.session_state.get("n_sent", 0) + len(msgs)
            st.session_state.decisions = decisions

    items = st.session_state.get("decisions", [])
    if not items:
        st.info("Inbox is empty.")
        return

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("⚠️ Needs you", sum(1 for x in items if x["decision"].behaviour in NEEDS_HUMAN))
    k2.metric("🟢 To confirm", sum(1 for x in items if x["decision"].behaviour is Behaviour.ALLOCATE))
    k3.metric("✅ Committed", len(desk.audit.load_all()))
    k4.metric("🕒 Total queue (days)", round(sum(desk.state.queues.values()), 1))

    # one tap = one behaviour: the five cases never stack on the page
    FILTERS = [Behaviour.ALLOCATE, Behaviour.REFUSE, Behaviour.IMPOSSIBLE,
               Behaviour.ASK, Behaviour.NO_DATA]
    picked = st.segmented_control(
        "Case", options=FILTERS,
        format_func=lambda b: BADGE[b][0],
        selection_mode="single", default=Behaviour.ALLOCATE)
    shown = [x for x in items
             if x["decision"].behaviour is picked
             or (picked is Behaviour.NO_DATA
                 and x["decision"].behaviour is Behaviour.ANSWER)]
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
            st.caption(item["msg"])
            render_decision(d, desk)


# ---------------- 📊 dashboard ----------------

def render_dashboard(desk):
    st.caption("Live chat-side queue = 2026-04-01 snapshot + what this session "
               "has committed. Bars jump after each confirm.")
    import pandas as pd

    names, snapshot, live, cost, defect = [], [], [], [], []
    for wid, w in desk.workshops.workshops.items():
        names.append(w.name)
        snapshot.append(w.queue0)
        live.append(round(desk.state.queues[wid], 2))
        cost.append(w.cost)
        defect.append(w.defect_rate)

    st.markdown("**📡 Workshop queue levels**")
    queues = pd.DataFrame({"workshop": names,
                           "4/1 snapshot": snapshot, "Live queue": live})
    st.bar_chart(queues, x="workshop", y=["4/1 snapshot", "Live queue"],
                 color=[BLUE_PALE, BLUE_DEEP],
                 x_label="Workshop", y_label="Queue (days)")

    st.markdown("**🧬 Cost × defect rate (bubble = live queue)**")
    trade = pd.DataFrame({"cost_per_pc": cost, "defect_rate": defect,
                          "queue_days": live, "workshop": names})
    st.scatter_chart(trade, x="cost_per_pc", y="defect_rate",
                     size="queue_days", color=[BLUE_SOFT],
                     x_label="Cost ($/pc)", y_label="Defect rate")


# ---------------- 🧾 records ----------------

def render_recent(desk):
    """Step 7 — the record the group chat never had."""
    top_l, top_r = st.columns([3, 1])
    top_l.caption("The audit log is an append-only file: refreshing does not "
                  "reset it, and re-committing the same order is refused "
                  "(never overwritten, never double-counted). Use the button "
                  "on the right to zero the demo.")
    if top_r.button("↺ Reset demo", use_container_width=True,
                    help="Archive the current audit log, clear the session, "
                         "and reset queues to the 4/1 snapshot"):
        import datetime as _dt
        path = desk.audit.path
        if path.exists():
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            path.rename(path.with_name(f"audit_log.{stamp}.bak.jsonl"))
        st.session_state.clear()   # desk rebuilt -> queues back to snapshot
        st.rerun()

    records = desk.audit.load_all()
    if not records:
        st.info("No committed records yet.")
        return
    for r in reversed(records):
        card(f"<b>{r.record_id}</b> · {r.order_id} → {r.workshop_id} "
             f"({r.pieces} pcs)<br>"
             f"<span class='muted'>{r.committed_by} · {r.committed_at} · "
             f"queue {r.queue_before} → {r.queue_after} d</span>")


def main():
    st.set_page_config(page_title="Dispatch Desk", layout="wide",
                       initial_sidebar_state="auto")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🛰️ Dispatch Desk")

    desk = get_desk()
    tab_main, tab_dash, tab_recent = st.tabs(
        ["🗂 Desk", "📊 Dashboard", "🧾 Records"])

    with tab_main:
        col_work, col_chat = st.columns([7, 3])
        with col_work:
            render_inbox(desk)
        with col_chat:
            render_chat_log(desk)
    with tab_dash:
        render_dashboard(desk)
    with tab_recent:
        render_recent(desk)


if __name__ == "__main__":
    main()
