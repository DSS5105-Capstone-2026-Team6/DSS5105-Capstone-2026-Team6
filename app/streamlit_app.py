"""
streamlit_app — the dispatcher's phone-first desk UI.

The only bridge to the backend is the DispatchDesk facade: handle_message()
turns one pasted chat line into a Decision, confirm() commits it and writes
the audit record. This file renders Decisions and captures taps; it holds no
business logic.

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

BADGE = {
    Behaviour.ALLOCATE: ("🟢 ALLOCATE", "#d3f9d8"),
    Behaviour.REFUSE: ("🔴 REFUSE", "#ffe3e3"),
    Behaviour.IMPOSSIBLE: ("🟠 IMPOSSIBLE", "#ffe8cc"),
    Behaviour.ASK: ("🔵 ASK", "#d0ebff"),
    Behaviour.ANSWER: ("⚪ ANSWER", "#e9ecef"),
    Behaviour.NO_DATA: ("⚪ NO DATA", "#e9ecef"),
}

CSS = """
<style>
.card {
    border: 1px solid #dee2e6; border-radius: 12px;
    padding: 12px 14px; margin: 8px 0; background: #fff;
}
.card.chosen { border: 2px solid #2f9e44; background: #f4fbf5; }
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
    secrets.toml, and merely touching st.secrets raises — hence the guard."""
    if "desk" not in st.session_state:
        try:
            try:
                secrets = dict(st.secrets)
            except Exception:
                secrets = {}
            for var in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
                if secrets.get(var) and not os.environ.get(var):
                    os.environ[var] = secrets[var]
            st.session_state.desk = DispatchDesk()
        except Exception as exc:  # missing API key, unreadable data...
            st.error(f"Backend failed to start: {exc}")
            st.stop()
    return st.session_state.desk


def card(html):
    st.markdown(f'<div class="card">{html}</div>', unsafe_allow_html=True)


def split_chat_dump(text):
    """Split a pasted group-chat dump into single messages. A line matching
    the inbox envelope (R23 [08:29] Priya: ...) starts a new message;
    continuation lines belong to the previous one. One message -> [text]."""
    msgs, current = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
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
    st.markdown("**候选车间**")
    for i, c in enumerate(decision.candidates[:3]):
        is_chosen = decision.chosen and c.workshop_id == decision.chosen.workshop_id
        slack = ""
        if decision.parsed.due_date:
            from datetime import date
            slack_days = (date.fromisoformat(decision.parsed.due_date)
                          - date.fromisoformat(c.estimated_finish)).days
            slack = (f"{slack_days} 天提前" if slack_days >= 0
                     else f"{-slack_days} 天迟到")
        body = (f'<b>{c.name} ({c.workshop_id})</b>'
                + (" ⭐" if is_chosen else "")
                + f'<br>完工 {c.estimated_finish} · {slack}'
                + f'<br>成本 {c.cost:.2f} · 缺陷率 {c.defect_risk:.2f}')
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
        st.success(f"已提交 {r.record_id} — {r.order_id} → {r.workshop_id}")
        return
    st.markdown("**拍板（推荐只是参考，可改选）**")
    from dataclasses import replace
    for c in decision.candidates[:3]:
        is_chosen = decision.chosen and c.workshop_id == decision.chosen.workshop_id
        label = f"✅ 确认 {c.name} ({c.workshop_id})" + (" ⭐ 系统推荐" if is_chosen else "")
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
    st.markdown("**可复制回复**")
    st.code(decision.explanation, language=None)


def render_recent(desk):
    """Step 7 — the record the group chat never had."""
    records = desk.audit.load_all()
    if not records:
        st.info("还没有已确认的记录。")
        return
    for r in reversed(records):
        card(f"<b>{r.record_id}</b> · {r.order_id} → {r.workshop_id} "
             f"({r.pieces} pcs)<br>"
             f"<span class='muted'>{r.committed_by} · {r.committed_at} · "
             f"队列 {r.queue_before} → {r.queue_after} 天</span>")


def main():
    st.set_page_config(page_title="Dispatch Desk", layout="centered",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🧶 Dispatch Desk")

    desk = get_desk()
    tab_chat, tab_recent = st.tabs(["📨 处理请求", "📋 最近决定"])

    with tab_chat:
        text = st.text_area("粘贴群聊消息", height=140,
                            placeholder="Ravi: ORD-063 — 100 cardigans, make Apr 29.\n"
                                        "支持整段群聊粘贴，自动按 Rxx 前缀逐条调度")
        if st.button("发送", use_container_width=True, type="primary") and text.strip():
            n = st.session_state.get("n_sent", 0)
            if n >= 40:
                st.warning("本会话请求已达上限（40 条），请重新打开页面。")
            else:
                decisions = []
                msgs = split_chat_dump(text.strip())
                st.session_state.n_sent = n + len(msgs)
                for i, msg in enumerate(msgs, 1):
                    with st.spinner(f"调度中（{i}/{len(msgs)}：{msg[:40]}...）"):
                        decisions.append(desk.handle_message(msg, requester="dispatcher"))
                st.session_state.decisions = decisions

        decisions = st.session_state.get("decisions", [])
        for i, decision in enumerate(decisions, 1):
            if len(decisions) > 1:
                st.divider()
                st.markdown(f"**#{i}** · `{decision.parsed.order_id or decision.behaviour.value}`")
            render_understood(decision)
            render_candidates(decision)
            render_confirm(decision, desk)
            render_reply(decision)

    with tab_recent:
        render_recent(desk)


if __name__ == "__main__":
    main()
