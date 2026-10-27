"""
streamlit_app — the dispatcher's desk UI.

The only bridge to the backend is the DispatchDesk facade: handle_message()
turns one chat line into a Decision, confirm() commits it and writes the
audit record. This file renders Decisions and captures taps; it holds no
business logic.

Layout: three tabs — 🗂 inbox (batch worklist, bucketed by behaviour),
📊 dashboard (live queue charts), 🧾 records (append-only audit feed);
the chat panel rides next to the inbox for multi-turn follow-ups.

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
    API key: locally from .env (load_api_key); on Streamlit Community Cloud
    from st.secrets, mirrored into os.environ. Locally there is no
    secrets.toml, and merely touching st.secrets raises — hence the guard.
    Hot-reload guard: a desk created before a code update may lack newer
    agent methods; rebuild it rather than crash."""
    desk = st.session_state.get("desk")
    if desk is not None and not hasattr(desk.agent, "new_conversation"):
        desk = None
    if desk is None:
        try:
            try:
                secrets = dict(st.secrets)
            except Exception:
                secrets = {}
            for var in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
                if secrets.get(var) and not os.environ.get(var):
                    os.environ[var] = secrets[var]
            desk = DispatchDesk()
            st.session_state.desk = desk
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
    gets its own confirm button, not just the top pick. A rerun never
    commits twice."""
    key = f"committed-{id(decision)}"
    if not decision.candidates or decision.parsed.order_id is None:
        return
    if key in st.session_state:
        r = st.session_state[key]
        st.success(f"⚡ Committed {r.record_id} — {r.order_id} → {r.workshop_id}")
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
            st.session_state[key] = record
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
    render_understood(decision)
    render_candidates(decision)
    render_confirm(decision, desk)
    render_options(decision)
    render_reply(decision)


def _budget_ok(extra=1):
    """Per-session request cap (Risk 6): the hosted demo shares one key."""
    n = st.session_state.get("n_sent", 0)
    if n + extra > 40:
        st.warning("Session request cap reached (40). Please reopen the page.")
        return False
    return True


# ---------------- 🗂 inbox ----------------

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
                    decisions.append(
                        {"msg": msg,
                         "decision": desk.handle_message(msg, requester="dispatcher")})
            st.session_state.n_sent = st.session_state.get("n_sent", 0) + len(msgs)
            st.session_state.decisions = decisions

    items = st.session_state.get("decisions", [])
    if not items:
        st.info("Inbox is empty.")
        return

    buckets = {
        "⚠️ Needs you": [x for x in items if x["decision"].behaviour in NEEDS_HUMAN],
        "⚡ To confirm": [x for x in items if x["decision"].behaviour is Behaviour.ALLOCATE],
        "💬 Answered": [x for x in items if x["decision"].behaviour is Behaviour.ANSWER],
    }

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("⚠️ Needs you", len(buckets["⚠️ Needs you"]))
    k2.metric("⚡ To confirm", len(buckets["⚡ To confirm"]))
    k3.metric("✅ Committed", len(desk.audit.load_all()))
    k4.metric("🕒 Total queue (days)", round(sum(desk.state.queues.values()), 1))

    # compact worklist: one row per request, details behind an expander
    n = 0
    for bucket, bucket_items in buckets.items():
        if not bucket_items:
            continue
        st.markdown(f"**{bucket} ({len(bucket_items)})**")
        for item in bucket_items:
            n += 1
            d = item["decision"]
            with st.expander(_row_label(n, item),
                             expanded=bucket == "⚠️ Needs you"):
                st.caption(item["msg"])
                render_decision(d, desk)


# ---------------- 💬 chat ----------------

def render_chat(desk):
    st.markdown("**💬 Chat (follow-ups / clarifications)**")
    top_l, top_r = st.columns([3, 1])
    top_l.caption("Follow-ups share one conversation with the messages above; "
                  "tapping a ▶ option fills the box.")
    if top_r.button("🔄 New chat", use_container_width=True):
        desk.agent.new_conversation()
        st.session_state.turns = []

    for turn in st.session_state.get("turns", []):
        with st.chat_message("user", avatar="🧑‍🔧"):
            st.write(turn["user"])
        with st.chat_message("assistant", avatar="🤖"):
            render_decision(turn["decision"], desk)

    queued = st.session_state.pop("queued_input", None)
    prompt = st.chat_input("Follow up, or tap a ▶ option above") or queued
    if prompt and _budget_ok():
        st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
        with st.spinner("Working..."):
            decision = desk.handle_message(prompt, requester="dispatcher")
        st.session_state.setdefault("turns", []).append(
            {"user": prompt, "decision": decision})
        st.rerun()


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
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🛰️ Dispatch Desk")

    desk = get_desk()
    tab_main, tab_dash, tab_recent = st.tabs(
        ["🗂 Inbox", "📊 Dashboard", "🧾 Records"])

    with tab_main:
        col_inbox, col_chat = st.columns([5, 4])
        with col_inbox:
            render_inbox(desk)
        with col_chat:
            render_chat(desk)
    with tab_dash:
        render_dashboard(desk)
    with tab_recent:
        render_recent(desk)


if __name__ == "__main__":
    main()
