"""
ui_inbox — the Desk tab's intake and worklist: paste/upload/sample entry,
the dispatch loop, KPI row, behaviour filter, and one expander per request.

Card rendering lives in ui_cards.py (render_decision); the confirmation-flow
helpers (_budget_ok, _log_exchange, _norm_msg) live in app.streamlit_app
because the safety tests exec them straight from that file's AST — so they
are imported lazily inside the functions that need them.
"""

import streamlit as st

from desk.contracts import Behaviour, Decision
from desk.chat_dump import ENVELOPE, split_chat_dump
from desk.budget import BudgetExceeded
from desk.tools import flag_at_risk
from app.ui_shared import BADGE, NEEDS_HUMAN, _sync_anchor, scroll_to_anchor
from app.ui_cards import render_decision


def _save_thread(decision, desk):
    """Snapshot the agent's current thread as this item's conversation."""
    from app.streamlit_app import _norm_msg
    st.session_state[f"conv-{id(decision)}"] = [_norm_msg(m)
                                                for m in desk.agent.history]


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


def _parser_controls(text, desk):
    """LLM parser tab: Parse | Dispatch | Clear. Dispatch unlocks only
    after a successful parse of exactly the text now in the box; the
    parse result is drawn as cards below the buttons. Returns True when
    Dispatch was clicked."""
    from desk.llm_parser import parse_message
    from app.ui_parser import render_parse_result
    b_parse, b_send, b_clear = st.columns([2, 4, 1])
    # never disabled: a text area only sends its value on blur / Ctrl+Enter,
    # so "disabled while empty" kept Parse grey right after typing. The
    # click itself blurs the box, and this run already sees the new text.
    if b_parse.button("Parse", use_container_width=True, key="llm_parse_btn"):
        if not text.strip():
            st.warning("Type or paste a message first.")
        else:
            with st.spinner("Parsing…"):
                st.session_state.llm_parse_result = parse_message(text, desk.agent)
                st.session_state.llm_parsed_text = text
    result = st.session_state.get("llm_parse_result")
    parsed_ok = (result is not None and "error" not in result
                 and st.session_state.get("llm_parsed_text") == text and text.strip())

    def clear():
        st.session_state.llm_parse_text = ""
        st.session_state.pop("llm_parse_result", None)
        st.session_state.pop("llm_parsed_text", None)
    b_clear.button("Clear", use_container_width=True, key="llm_clear", on_click=clear)
    clicked = b_send.button("Dispatch", use_container_width=True, type="primary",
                            key="llm_dispatch", disabled=not parsed_ok,
                            help=None if parsed_ok else "Parse this message first")
    if result is not None:
        if st.session_state.get("llm_parsed_text") != text:
            st.caption("The message changed since the last parse — parse again "
                       "to unlock Dispatch.")
        render_parse_result(result, desk.orders)
    return clicked


def next_open_item(shown, src_id, is_done):
    """The item to scroll to after committing decision `src_id`: the
    nearest uncommitted one below it, else the nearest uncommitted one
    above it, else None."""
    ids = [id(x["decision"]) for x in shown]
    i = ids.index(src_id) if src_id in ids else -1
    below = shown[i + 1:]
    above = shown[:i][::-1] if i >= 0 else []
    return next((x for x in below + above if not is_done(x["decision"])), None)


def render_inbox(desk):
    from app.streamlit_app import _budget_ok, _log_exchange
    st.caption("Feed the desk — paste chat lines, drop a file, load a sample "
               "inbox, or let the LLM parse one message first.")
    src = st.segmented_control(
        "source", ["Paste", "Upload file", "Sample inbox", "LLM parser"],
        default="Paste", label_visibility="collapsed", key="inbox_src")
    text = ""
    if src == "LLM parser":
        text = st.text_area("One freeform message — Parse first, then Dispatch",
                            height=120, key="llm_parse_text",
                            placeholder="Boss: ORD-045 — 150 vests for Cotton Club, "
                                        "due Apr 09. It's urgent.")
    elif src == "Paste":
        text = st.text_area("Paste group-chat messages", height=120,
                            placeholder="Ravi: ORD-063 — 100 cardigans, make Apr 29.",
                            key="paste_box")
    elif src == "Upload file":
        up = st.file_uploader("Drop a .txt chat dump here", type=["txt"],
                              key="inbox_file")
        if up is not None:
            text = up.getvalue().decode("utf-8")
            st.caption(f"{up.name} — {len(text.splitlines())} lines")
    else:
        from desk.config import DATA_DIR
        # any dispatch*.txt in data/ is a loadable inbox: the dev 30, the
        # held-out 20, and future full sets (120 requests)
        samples = sorted(DATA_DIR.glob("dispatch*.txt"))
        labels = {p.name: f"{p.stem} · "
                  + str(sum(1 for line in p.read_text(encoding='utf-8').splitlines()
                            if line.strip() and not line.startswith('#')))
                  + " requests" for p in samples}
        choice = st.selectbox("Sample inbox", list(labels),
                              format_func=lambda n: labels[n],
                              key="inbox_sample")
        text = (DATA_DIR / choice).read_text(encoding="utf-8")
        st.caption(f"{choice} loaded")
    if src == "LLM parser":
        clicked = _parser_controls(text, desk)
    else:
        b_send, b_clear = st.columns([5, 1])
        # Clear empties the paste box only; results and the chat log stay
        if src == "Paste":
            b_clear.button("Clear", use_container_width=True,
                           on_click=lambda: st.session_state.update(paste_box=""))
        clicked = b_send.button("Dispatch", use_container_width=True, type="primary")
    if clicked and text.strip():
        msgs = split_chat_dump(text.strip())
        if _budget_ok(len(msgs)):
            st.session_state.dispatching = True   # locks the objective panel
            try:
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
            finally:
                st.session_state.dispatching = False   # unlock even on error
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
    # an order committed on another card (or earlier) counts as done too
    done_orders = {r.order_id for r in desk.audit.load_all()}

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
                st.metric("Committed", len({r.order_id for r in desk.audit.load_all()}))
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
        # (ui_cards / item chat set scroll_from to the committed decision):
        # the nearest open one BELOW first; if none is left below, the
        # nearest open one ABOVE (orders the user skipped for later)
        src_id = st.session_state.pop("scroll_from", None)
        if src_id is not None:
            nxt = next_open_item(shown, src_id, is_done)
            if nxt is not None:
                scroll_to_anchor(f"d{id(nxt['decision'])}")
