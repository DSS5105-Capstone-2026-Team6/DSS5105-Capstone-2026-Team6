"""
adapter/session.py — one Telegram chat <-> one DispatchDesk.

A ChatSession owns a DispatchDesk built with the "group" persona, so every
group/private chat gets isolated queues, history and audit. It also owns the
confirmation gate: the desk never commits on its own, and neither does the
adapter — a commit happens only when the member's follow-up text parses as
an explicit confirmation (desk.commit_intent_workshop, the same deterministic
detector the Streamlit UI uses).

No telegram imports here on purpose: everything is plain Python so the tests
can drive it with a fake desk.

    session = ChatSession(lambda: DispatchDesk(persona="group"))
    reply, options = session.handle("Ravi: ORD-063 — 100 cardigans", "Ravi")
    # ... agent replies with candidates; later, in the same chat:
    reply, _ = session.handle("yes", "Priya")     # commits the recommendation
"""

from dataclasses import replace

try:
    from desk.desk import commit_intent_workshop
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.desk import commit_intent_workshop

MAX_MESSAGE_LEN = 4096   # Telegram's per-message ceiling


def wants_bot(text, *, private, bot_username=""):
    """Trigger filter, applied BEFORE any LLM round-trip: private chats always
    talk to the desk; inside a group only an @mention does, so the agent never
    burns budget on chatter between members."""
    if not (text or "").strip():
        return False
    if private:
        return True
    return bool(bot_username) and f"@{bot_username.lower()}" in text.lower()


def strip_mention(text, bot_username):
    """Drop the '@bot' token from a group message, leaving the request."""
    if not bot_username:
        return (text or "").strip()
    return (text or "").replace(f"@{bot_username}", "").strip()


def split_reply(text, limit=MAX_MESSAGE_LEN):
    """Telegram rejects messages over 4096 chars; break at a newline where
    possible. Short replies come back as a single chunk."""
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


class ChatSession:
    """State for one chat: the desk, and the decision currently awaiting a
    human yes/no. handle() returns (reply_text, options) — the platform layer
    renders options as buttons and feeds the tapped one back in as text."""

    def __init__(self, make_desk):
        self.desk = make_desk()
        self.pending = None   # last decision with candidates, awaiting confirm

    def handle(self, text, requester=""):
        """One incoming message -> (reply, options). Confirmation is checked
        first; anything that is not an explicit commit goes to the agent."""
        text = (text or "").strip()
        if self.pending is not None:
            workshop_id = commit_intent_workshop(text, self.pending)
            if workshop_id is not None:
                return self._commit(workshop_id, requester)
        decision = self.desk.handle_message(text, requester=requester or None)
        if decision.candidates:
            self.pending = decision
        return decision.explanation or "(no reply)", list(decision.options)

    def _commit(self, workshop_id, requester):
        target = next((c for c in self.pending.candidates
                       if c.workshop_id == workshop_id), None)
        decision, self.pending = self.pending, None   # one shot, like the UI
        if target is None:
            return "That workshop is no longer among the candidates.", []
        try:
            record = self.desk.confirm(replace(decision, chosen=target),
                                       committed_by=requester or "group")
        except ValueError as exc:
            return f"Commit failed: {exc}", []
        return (f"Committed {record.record_id} — "
                f"{record.order_id} → {record.workshop_id}."), []
