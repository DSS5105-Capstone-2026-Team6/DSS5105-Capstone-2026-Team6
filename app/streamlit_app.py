"""
streamlit_app — the dispatcher's desk UI: entry point, auth gate, and the
confirmation-flow core.

The only bridge to the backend is the DispatchDesk facade: handle_message()
turns one chat line into a Decision, confirm() commits it and writes the
audit record. This file renders Decisions and captures taps; it holds no
business logic.

Layout: tab 🗂 desk = one full-width worklist, one row per request. A fourth
option beside the candidate buttons — "Other option (tell me)" — expands a
per-item conversation. The sidebar carries the provider/model selectors, a
running chat log and the returned-batch recorder.

Sections live in sibling modules: ui_shared (constants, card, scroll sync),
ui_inbox (worklist + cards), ui_dashboard (charts), ui_sidebar (chat log +
batch recorder), ui_records (ledger view).

NOTE: _replace_item, render_item_chat, _budget_ok, _norm_msg,
_log_exchange, _auth_token and _valid_auth_token must stay top-level defs in
THIS file — tests/test_dispatch_safety.py execs them straight from this
file's AST. Sibling modules import them lazily where needed.

Run from the project root:

    uv run streamlit run app/streamlit_app.py
"""

import hashlib
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from desk.contracts import Behaviour, Decision
from desk.desk import DispatchDesk
from desk.budget import BudgetExceeded
from desk.chat_dump import ENVELOPE, split_chat_dump  # re-exported for tests

from app.ui_shared import CSS, install_scroll_sync
from app.ui_inbox import render_inbox
from app.ui_dashboard import render_dashboard
from app.ui_sidebar import render_chat_log, render_performance_sidebar
from app.ui_records import render_recent


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
            st.error("Backend failed to start. Check the server configuration and provider key.")
            st.stop()
    return desk


# ---------------- per-item conversation (the 4th option) ----------------

def _norm_msg(m):
    """OpenAI SDK message objects -> plain dicts for session_state."""
    if hasattr(m, "model_dump"):
        return m.model_dump()
    return dict(m)


def _log_exchange(speaker, text, reply, link=None):
    """Append one exchange to the sidebar's running log. `link` ties the
    entry to its worklist card, for the scroll sync (see SCROLL_SYNC_JS)."""
    st.session_state.setdefault("chat_log", []).append(
        {"speaker": speaker, "text": text, "reply": reply, "link": link})


def _budget_ok(extra=1, cap=100):
    """Per-session request cap (Risk 6): the hosted demo shares one key.
    Temporarily raised from 40 to 100; the global hourly/daily API limits
    (API_CALLS_PER_HOUR / API_CALLS_PER_DAY) still apply across sessions.
    The cap lives here, not in a module constant, because the tests exec
    this function on its own."""
    n = st.session_state.get("n_sent", 0)
    if n + extra > cap:
        st.warning(f"Session request cap reached ({cap}). Please reopen the page.")
        return False
    return True


def _replace_item(previous, updated, reply):
    if updated is None:
        updated = Decision(request_id=previous.request_id, behaviour=Behaviour.ANSWER,
                           parsed=previous.parsed, explanation=reply)
    for item in st.session_state.get("decisions", []):
        if item["decision"] is previous or item.get("updating_id") == previous.decision_id:
            item["decision"] = updated
            item["updating_id"] = previous.decision_id
            break
    return updated


def render_item_chat(decision, desk):
    """The 4th-option conversation bound to ONE dispatch item. First shows
    every eligible workshop with its LIVE queue (re-read on each rerun, so
    the numbers move as soon as another dispatch commits); then the chat:
    ask anything, or name ANY candidate with an action word ('commit to
    W2', 'send it to Little Loom') to dispatch it — no LLM round."""
    key = f"conv-{id(decision)}"
    conv = st.session_state.setdefault(key, [])

    if decision.candidates:
        st.markdown("**🧭 All candidates · live queue**")
        for c in decision.candidates:
            live_q = desk.state.queues.get(c.workshop_id, 0.0)
            star = " ⭐" if (decision.recommended_split is None and decision.chosen
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
    if not _budget_ok():
        return
    st.session_state.n_sent = st.session_state.get("n_sent", 0) + 1
    desk.agent.history = [dict(m) for m in conv]
    # Invalidate old buttons before a request that may change the proposal.
    _replace_item(decision, None, "Updating proposal...")
    try:
        with st.spinner("Working..."):
            updated, record, reply = desk.follow_up(prompt, decision)
    except BudgetExceeded:
        _replace_item(decision, None, "Request limit reached. Please try again later.")
        st.warning("Request limit reached. Please try again later.")
        return
    except Exception:
        _replace_item(decision, None, "Request failed. Please request a new proposal.")
        st.error("Request failed. Please retry later; no confirmation was completed.")
        return
    conv.append({"role": "user", "content": prompt})
    conv.append({"role": "assistant", "content": reply})
    if record is not None:
        _replace_item(decision, decision, reply)
        st.session_state[f"committed-{id(decision)}"] = record
    else:
        replacement = _replace_item(decision, updated, reply)
        st.session_state[f"conv-{id(replacement)}"] = [_norm_msg(m) for m in desk.agent.history]
        # Fast cancellation/confirmation has no model turn to persist.
        if updated is None:
            st.session_state[f"conv-{id(replacement)}"] = conv
    _log_exchange("dispatcher", prompt, reply or "")
    st.rerun()


# ---------------- auth gate ----------------

AUTH_COOKIE = "desk_auth"
AUTH_DAYS = 30


def _auth_token(password):
    """What the device stores: an HMAC of the password, never the password
    itself. Changing APP_PASSWORD makes every old cookie stop working."""
    import time
    import secrets
    body = f"{int(time.time()) + AUTH_DAYS * 86400}.{secrets.token_hex(16)}"
    signature = hmac.new(str(password).encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _valid_auth_token(token, password):
    import time
    try:
        expires, nonce, signature = token.split(".")
        body = f"{expires}.{nonce}"
        expected = hmac.new(str(password).encode(), body.encode(), hashlib.sha256).hexdigest()
        return (time.time() < int(expires) <= time.time() + AUTH_DAYS * 86400
                and hmac.compare_digest(signature, expected))
    except (AttributeError, TypeError, ValueError):
        return False


def _device_token(action="get", token=""):
    """Read (or set / forget) the remember-me token in this browser's
    localStorage through a tiny two-way component (app/local_auth). Cookies
    don't work here: Streamlit Cloud's proxy never passes them to
    st.context.cookies. Returns None until the browser has answered."""
    import streamlit.components.v1 as components
    local_auth = components.declare_component(
        "local_auth", path=str(Path(__file__).parent / "local_auth"))
    return local_auth(action=action, name=AUTH_COOKIE, token=token,
                      key=f"local_auth_{action}", default=None)


def check_password():
    """Gate the desk behind APP_PASSWORD (st.secrets or env). Every
    Dispatch spends the owner's API key, so a public link must not be
    enough. No password configured fails closed unless local development
    explicitly opts out. A correct password is remembered on this device
    (localStorage) for AUTH_DAYS."""
    if (Path(__file__).parent.parent / ".env").exists():
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    try:
        expected = st.secrets.get("APP_PASSWORD")
    except Exception:          # no secrets.toml at all (local run)
        expected = None
    expected = expected or os.environ.get("APP_PASSWORD")
    if not expected:
        if os.environ.get("REQUIRE_APP_PASSWORD", "true").lower() == "false":
            return True
        st.error("APP_PASSWORD is required. Configure it in Streamlit Secrets before using this app.")
        return False
    if st.session_state.get("authed"):
        if st.session_state.get("remember_device"):
            # keep rendering until the browser confirms the token is saved
            saved = _device_token("set", st.session_state.remember_device)
            if saved == st.session_state.remember_device:
                del st.session_state["remember_device"]
        return True
    saved = _device_token("get")
    if saved and _valid_auth_token(str(saved), expected):
        st.session_state.authed = True
        st.rerun()
    pw = st.text_input("Password", type="password")
    if pw:
        from desk.budget import CallBudget, BudgetExceeded
        try:
            CallBudget().reserve(scope="login", limits=[(60, 30)])
        except BudgetExceeded:
            st.error("Too many sign-in attempts. Please try again later.")
            return False
    if pw and hmac.compare_digest(pw.encode(), str(expected).encode()):
        st.session_state.authed = True
        st.session_state.remember_device = _auth_token(expected)
        st.rerun()
    if pw:
        st.error("Wrong password.")
    return False


def main():
    st.set_page_config(page_title="Dispatch Desk", layout="wide",
                       initial_sidebar_state="auto")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🛰️ Dispatch Desk")
    if not check_password():
        st.stop()

    desk = get_desk()
    with st.sidebar:
        render_chat_log()
        render_performance_sidebar(desk)
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
