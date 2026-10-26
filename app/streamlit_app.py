"""
streamlit_app — the dispatcher's desk UI.

The only bridge to the backend is the DispatchDesk facade: handle_message()
turns one chat line into a Decision, confirm() commits it and writes the
audit record. This file renders Decisions and captures taps; it holds no
business logic.

Layout: four tabs — 🗂 inbox (batch worklist, bucketed by behaviour),
💬 chat (multi-turn follow-ups), 📊 dashboard (live queue charts, ECharts),
🧾 records (append-only audit feed).

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
    st.markdown("**🧭 候选车间**")
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
        st.success(f"⚡ 已提交 {r.record_id} — {r.order_id} → {r.workshop_id}")
        return
    st.markdown("**⚙️ 拍板（推荐只是参考，可改选）**")
    from dataclasses import replace
    for c in decision.candidates[:3]:
        is_chosen = decision.chosen and c.workshop_id == decision.chosen.workshop_id
        label = f"▶ 确认 {c.name} ({c.workshop_id})" + (" ⭐ 系统推荐" if is_chosen else "")
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
    st.markdown("**📤 可复制回复**")
    st.code(decision.explanation, language=None)


def _queue_input(text):
    """Tappable option -> put the order id into the chat box on next rerun."""
    st.session_state.queued_input = text


def render_options(decision):
    """ASK decisions carry tappable choices (journey step 6): one tap
    answers the clarifying question instead of typing."""
    if not decision.options:
        return
    st.markdown("**⌨️ 点选回复**")
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
        st.warning("本会话请求已达上限（40 条），请重新打开页面。")
        return False
    return True


# ---------------- 🗂 inbox ----------------

def _row_label(i, item):
    d = item["decision"]
    label, _ = BADGE[d.behaviour]
    what = d.parsed.order_id or item["msg"][:24]
    return f"#{i} · {what} · {label.split()[1]}"


def render_inbox(desk):
    st.caption("整段群聊粘贴进来，按 Rxx 前缀逐条调度（各条相互独立，"
               "不共享上下文）。")
    text = st.text_area("粘贴群聊消息", height=120,
                        placeholder="Ravi: ORD-063 — 100 cardigans, make Apr 29.")
    if st.button("🚀 调度", use_container_width=True, type="primary") and text.strip():
        msgs = split_chat_dump(text.strip())
        if _budget_ok(len(msgs)):
            decisions = []
            for i, msg in enumerate(msgs, 1):
                desk.agent.new_conversation()  # inbox lines are independent
                with st.spinner(f"调度中（{i}/{len(msgs)}：{msg[:40]}...）"):
                    decisions.append(
                        {"msg": msg,
                         "decision": desk.handle_message(msg, requester="dispatcher")})
            st.session_state.n_sent = st.session_state.get("n_sent", 0) + len(msgs)
            st.session_state.decisions = decisions

    items = st.session_state.get("decisions", [])
    if not items:
        st.info("收件箱为空。")
        return

    buckets = {
        "⚠️ 需人工": [x for x in items if x["decision"].behaviour in NEEDS_HUMAN],
        "⚡ 待拍板": [x for x in items if x["decision"].behaviour is Behaviour.ALLOCATE],
        "💬 已答复": [x for x in items if x["decision"].behaviour is Behaviour.ANSWER],
    }

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("⚠️ 需人工", len(buckets["⚠️ 需人工"]))
    k2.metric("⚡ 待拍板", len(buckets["⚡ 待拍板"]))
    k3.metric("✅ 已提交", len(desk.audit.load_all()))
    k4.metric("🕒 总队列(天)", round(sum(desk.state.queues.values()), 1))

    # compact worklist: one row per request, details behind an expander
    n = 0
    for bucket, bucket_items in buckets.items():
        if not bucket_items:
            continue
        st.markdown(f"**{bucket}（{len(bucket_items)}）**")
        for item in bucket_items:
            n += 1
            d = item["decision"]
            with st.expander(_row_label(n, item),
                             expanded=bucket == "⚠️ 需人工"):
                st.caption(item["msg"])
                render_decision(d, desk)


# ---------------- 💬 chat ----------------

def render_chat(desk):
    st.markdown("**💬 对话（追问 / 补充）**")
    top_l, top_r = st.columns([3, 1])
    top_l.caption("追问与上文共用一个会话；点 ▶ 选项按钮自动填入。")
    if top_r.button("🔄 新会话", use_container_width=True):
        desk.agent.new_conversation()
        st.session_state.turns = []

    for turn in st.session_state.get("turns", []):
        with st.chat_message("user", avatar="🧑‍🔧"):
            st.write(turn["user"])
        with st.chat_message("assistant", avatar="🤖"):
            render_decision(turn["decision"], desk)

    queued = st.session_state.pop("queued_input", None)
    prompt = st.chat_input("补充说明，或点上方 ▶ 选项") or queued
    if prompt and _budget_ok():
        st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
        with st.spinner("调度中..."):
            decision = desk.handle_message(prompt, requester="dispatcher")
        st.session_state.setdefault("turns", []).append(
            {"user": prompt, "decision": decision})
        st.rerun()


# ---------------- 📊 dashboard ----------------

def render_dashboard(desk):
    st.caption("实时聊天侧队列 = 2026-04-01 快照 + 本会话已提交的单。"
               "每次拍板后柱子会跳。")
    import pandas as pd

    names, snapshot, live, cost, defect = [], [], [], [], []
    for wid, w in desk.workshops.workshops.items():
        names.append(w.name)
        snapshot.append(w.queue0)
        live.append(round(desk.state.queues[wid], 2))
        cost.append(w.cost)
        defect.append(w.defect_rate)

    st.markdown("**📡 车间队列水位**")
    queues = pd.DataFrame({"workshop": names,
                           "4/1 快照": snapshot, "实时队列": live})
    st.bar_chart(queues, x="workshop", y=["4/1 快照", "实时队列"],
                 x_label="车间", y_label="队列（天）")

    st.markdown("**🧬 成本 × 缺陷率（点大小 = 当前队列）**")
    trade = pd.DataFrame({"cost_per_pc": cost, "defect_rate": defect,
                          "queue_days": live, "workshop": names})
    st.scatter_chart(trade, x="cost_per_pc", y="defect_rate",
                     size="queue_days", color="workshop",
                     x_label="成本 ($/pc)", y_label="缺陷率")


# ---------------- 🧾 records ----------------

def render_recent(desk):
    """Step 7 — the record the group chat never had."""
    top_l, top_r = st.columns([3, 1])
    top_l.caption("审计日志是 append-only 文件，刷新不重置；同一订单重复"
                  "提交会被拒绝（不会覆盖也不会加总）。演示要清零请用右侧按钮。")
    if top_r.button("↺ 重置演示", use_container_width=True,
                    help="归档当前审计日志，清空会话，队列回到 4/1 快照"):
        import datetime as _dt
        path = desk.audit.path
        if path.exists():
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            path.rename(path.with_name(f"audit_log.{stamp}.bak.jsonl"))
        st.session_state.clear()   # desk 重建 → 队列回快照
        st.rerun()

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
    st.set_page_config(page_title="Dispatch Desk", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🛰️ Dispatch Desk")

    desk = get_desk()
    tab_main, tab_dash, tab_recent = st.tabs(
        ["🗂 收件箱", "📊 面板", "🧾 记录"])

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
