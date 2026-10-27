"""
streamlit_app — the dispatcher's desk UI.

The only bridge to the backend is the DispatchDesk facade: handle_message()
turns one chat line into a Decision, confirm() commits it and writes the
audit record. This file renders Decisions and captures taps; it holds no
business logic.

Layout: tab 🗂 desk = one full-width worklist, one row per request. The
copyable reply lives under its own dispatch item. A fourth option beside
the candidate buttons — "Other option (tell me)" — expands a per-item
conversation: it opens with every eligible workshop and its LIVE queue,
then takes free text; naming ANY candidate with an action word ("commit
to W2") dispatches it without an extra LLM round. The sidebar carries the
provider/model selectors and a running chat log of every exchange.

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
from desk.chat_dump import ENVELOPE, split_chat_dump

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
        model_entry = st.selectbox(
            "Model", options=PROVIDERS[provider]["models"],
            format_func=lambda m: m[1], key="model_sel")
        model = model_entry[0]            # api id; [1] is the display label
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


# ---------------- chat log (sidebar) ----------------

def _log_exchange(speaker, text, reply, link=None):
    """Append one exchange to the sidebar's running log. `link` ties the
    entry to its worklist card, for the scroll sync (see SCROLL_SYNC_JS)."""
    st.session_state.setdefault("chat_log", []).append(
        {"speaker": speaker, "text": text, "reply": reply, "link": link})


def _sync_anchor(link):
    """Invisible marker the scroll-sync script looks for."""
    st.markdown(f'<span class="sync-anchor" data-sync="{link}"></span>',
                unsafe_allow_html=True)


def render_chat_log():
    """Sidebar record of everything the desk has handled, newest at the
    bottom. Read-only — actions live in the worklist."""
    log = st.session_state.get("chat_log", [])
    st.markdown("**💬 Chat log**")
    st.caption(f"{len(log)} messages")
    with st.container(height=420, border=False):
        for turn in log:
            with st.chat_message("user", avatar="🧑‍🔧"):
                if turn.get("link"):
                    _sync_anchor(turn["link"])
                st.write(f"**{turn['speaker']}:** {turn['text']}")
            with st.chat_message("assistant", avatar="🤖"):
                st.text(turn["reply"] if turn["reply"] else "(no reply)")


# ---------------- scroll sync: worklist card -> chat log ----------------

# Streamlit has no scroll events, so a tiny script is injected into the page
# (components.html runs same-origin, so it can reach window.parent). On
# every scroll of the main area it finds the worklist card at the middle of
# the screen, scrolls the sidebar chat log to the message with the same
# data-sync id and flashes it grey twice. Installed once per page (versioned, so a newer
# script replaces an older one); reruns don't stack it.
SCROLL_SYNC_JS = """
(function () {
  const w = window, doc = document, VERSION = 3;
  const old = w.__deskScrollSync;
  if (old && old.version === VERSION) return;
  if (old) doc.removeEventListener("scroll", old.onScroll, true);
  const css = doc.getElementById("desk-sync-css") || doc.createElement("style");
  css.id = "desk-sync-css";
  css.textContent = `
    @keyframes desk-blink { 0%,50%,100% { background: transparent; }
                            25%,75% { background: #e9ecef; } }
    .desk-blink { animation: desk-blink 1.2s ease-in-out 1; border-radius: 8px; }`;
  doc.head.appendChild(css);
  let active = null, timer = null;
  function scrollParent(el) {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const oy = w.getComputedStyle(p).overflowY;
      if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) return p;
    }
    return null;
  }
  function sync() {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) return;
    const cards = [...doc.querySelectorAll(".sync-anchor")]
      .filter(a => !sidebar.contains(a));
    // the card at the middle of the screen wins (nearest one if the
    // middle falls in a gap between cards)
    const mid = w.innerHeight / 2;
    let link = null, best = Infinity;
    for (const a of cards) {
      const box = (a.closest('[data-testid="stExpander"]') || a).getBoundingClientRect();
      if (!box.height) continue;
      const dist = mid < box.top ? box.top - mid : mid > box.bottom ? mid - box.bottom : 0;
      if (dist < best) { best = dist; link = a.dataset.sync; }
    }
    if (!link || link === active) return;
    const anchor = sidebar.querySelector('.sync-anchor[data-sync="' + link + '"]');
    if (!anchor) return;
    active = link;
    const msg = anchor.closest('[data-testid="stChatMessage"]') || anchor.parentElement;
    const box = scrollParent(msg);
    if (box) box.scrollTo({ top: box.scrollTop + msg.getBoundingClientRect().top
                                 - box.getBoundingClientRect().top - 8,
                            behavior: "smooth" });
    msg.classList.remove("desk-blink");
    void msg.offsetWidth;            // restart the animation
    msg.classList.add("desk-blink");
  }
  function onScroll(e) {
    const sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if (sidebar && e.target.nodeType === 1 && sidebar.contains(e.target)) return;
    w.clearTimeout(timer);
    timer = w.setTimeout(sync, 150);
  }
  doc.addEventListener("scroll", onScroll, true);
  w.__deskScrollSync = { version: VERSION, onScroll: onScroll };
})();
"""


def install_scroll_sync():
    """Copy the script into the app page itself (not this component's
    iframe), so it keeps running when Streamlit re-renders the iframe."""
    import json
    import streamlit.components.v1 as components
    components.html(
        "<script>const d = window.parent.document;"
        "const cur = window.parent.__deskScrollSync;"
        "if (!cur || cur.version !== 3) {"
        " const s = d.createElement('script');"
        f" s.textContent = {json.dumps(SCROLL_SYNC_JS)};"
        " d.head.appendChild(s); }</script>", height=0)


# ---------------- per-item conversation (the 4th option) ----------------

def _norm_msg(m):
    """OpenAI SDK message objects -> plain dicts for session_state."""
    if hasattr(m, "model_dump"):
        return m.model_dump()
    return dict(m)


def _save_thread(decision, desk):
    """Snapshot the agent's current thread as this item's conversation."""
    st.session_state[f"conv-{id(decision)}"] = [_norm_msg(m)
                                                for m in desk.agent.history]


def render_item_chat(decision, desk):
    """The 4th-option conversation bound to ONE dispatch item. First shows
    every eligible workshop with its LIVE queue (re-read on each rerun, so
    the numbers move as soon as another dispatch commits); then the chat:
    ask anything, or name ANY candidate with an action word ('commit to
    W2', 'send it to Little Loom') to dispatch it — no LLM round."""
    from desk.desk import commit_intent_workshop
    key = f"conv-{id(decision)}"
    conv = st.session_state.setdefault(key, [])

    if decision.candidates:
        st.markdown("**🧭 All candidates · live queue**")
        for c in decision.candidates:
            live_q = desk.state.queues.get(c.workshop_id, 0.0)
            star = " ⭐" if (decision.chosen
                             and c.workshop_id == decision.chosen.workshop_id) else ""
            st.markdown(f"- **{c.name} ({c.workshop_id})**{star} — "
                        f"queue {live_q:.1f} d · finish {c.estimated_finish} · "
                        f"cost {c.cost:.2f} · defect {c.defect_risk:.2f}")

    with st.container(height=240, border=False):
        for m in conv:
            role, content = m.get("role"), m.get("content")
            if role == "user":
                with st.chat_message("user", avatar="🧑‍🔧"):
                    st.text(content or "")
            elif role == "assistant" and content:
                with st.chat_message("assistant", avatar="🤖"):
                    st.text(content)

    with st.form(key=f"form-{id(decision)}", clear_on_submit=True):
        prompt = st.text_input("Tell me",
                               label_visibility="collapsed",
                               placeholder="Tell me — 'why not W4?', 'commit to W2'...")
        sent = st.form_submit_button("Send")
    if not (sent and prompt):
        return
    wid = commit_intent_workshop(prompt, decision)
    if (wid is not None and decision.candidates
            and decision.parsed.order_id):
        from dataclasses import replace
        target = next((c for c in decision.candidates
                       if c.workshop_id == wid), None)
        try:
            record = desk.confirm(replace(decision, chosen=target),
                                  committed_by="dispatcher")
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state[f"committed-{id(decision)}"] = record
        line = (f"Committed {record.record_id} — "
                f"{record.order_id} → {record.workshop_id}.")
        conv.append({"role": "user", "content": prompt})
        conv.append({"role": "assistant", "content": line})
        _log_exchange("dispatcher", prompt, line)
    else:
        if not _budget_ok():
            return
        st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
        desk.agent.history = [dict(m) for m in conv]   # continue THIS thread
        with st.spinner("Working..."):
            reply = desk.agent.chat(prompt)
        st.session_state[key] = [_norm_msg(m) for m in desk.agent.history]
        _log_exchange("dispatcher", prompt, reply or "")
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
    """Step 4 — one confirm button per top candidate (the recommendation is
    advisory). The fourth option lives in render_decision, not here, so it
    is available even when there are no candidates (ASK flows)."""
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
            line = (f"Committed {record.record_id} — "
                    f"{record.order_id} → {record.workshop_id}.")
            _log_exchange("dispatcher", f"(button) {c.name} ({c.workshop_id})",
                          line)
            st.rerun()


def render_decision(decision, desk):
    """Pre-commit: understood / candidates / confirm buttons, plus the 4th
    option — an expander with the live candidate board and the per-item
    conversation (the agent's reply shows there, first bubble).
    Post-commit: a single line — the confirm UI deletes itself."""
    r = st.session_state.get(f"committed-{id(decision)}")
    if r is not None:
        st.success(f"⚡ Committed {r.record_id} — {r.order_id} → {r.workshop_id}")
        return
    render_understood(decision)
    render_candidates(decision)
    render_confirm(decision, desk)
    # the 4th option, available on every uncommitted item (incl. ASK items
    # with no candidates): an expander — st.chat_input/popover cannot hold
    # a working chat input, so the dialog uses a text form
    with st.expander("💬 Other option (tell me)"):
        render_item_chat(decision, desk)


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
                    decision = desk.handle_message(msg, requester="dispatcher")
                    decisions.append({"msg": msg, "decision": decision})
                    _save_thread(decision, desk)   # per-item conversation seed
                    env = ENVELOPE.match(msg)
                    _log_exchange(env.group(3) if env else "chat",
                                  env.group(4) if env else msg,
                                  decision.explanation,
                                  link=f"d{id(decision)}")
            st.session_state.n_sent = st.session_state.get("n_sent", 0) + len(msgs)
            st.session_state.decisions = decisions

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
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("⚠️ Needs you", sum(1 for x in items if x["decision"].behaviour in NEEDS_HUMAN))
    k2.metric("🟢 To confirm", to_confirm)
    k3.metric("✅ Committed", len(desk.audit.load_all()))
    k4.metric("🕒 Total queue (days)", round(sum(desk.state.queues.values()), 1))

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
    with st.sidebar:
        render_chat_log()
    tab_main, tab_dash, tab_recent = st.tabs(
        ["🗂 Desk", "📊 Dashboard", "🧾 Records"])

    with tab_main:
        render_inbox(desk)
    install_scroll_sync()
    with tab_dash:
        render_dashboard(desk)
    with tab_recent:
        render_recent(desk)


if __name__ == "__main__":
    main()
