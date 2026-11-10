"""
adapter/session.py — one Telegram chat <-> one DispatchDesk.

A ChatSession owns a DispatchDesk built with the "group" persona, so every
group/private chat has its own conversation and a shared allocation ledger. It also owns the
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


from uuid import uuid4

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
    import re
    return re.sub(r"@" + re.escape(bot_username) + r"\b", "", text or "", flags=re.I).strip()


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
        self.options_token = uuid4().hex
        self.options = []

    def handle(self, text, requester=""):
        """One incoming message -> (reply, options). Confirmation is checked
        first; anything that is not an explicit commit goes to the agent."""
        from desk.confirmation import looks_like_confirmation
        from desk.desk import CANCEL_REPLY
        text = (text or "").strip()
        self.options_token = uuid4().hex
        self.options = []
        if self.pending is None and looks_like_confirmation(text):
            # A yes with no open proposal means the process restarted (the
            # pending proposal lives in memory) or the proposal lapsed. Say
            # so plainly instead of spending an LLM round on a bare "yes".
            return ("Nothing is awaiting confirmation right now — a bot "
                    "restart clears pending proposals. Send the order line "
                    "again and I'll re-rank it."), []
        if self.pending is not None:
            previous, self.pending = self.pending, None
            decision, record, reply = self.desk.follow_up(text, previous, requester or "group")
            if record is None and decision is None and reply != CANCEL_REPLY:
                # The follow-up was answered without re-ranking (no commit,
                # no cancel): keep the proposal open so a later "yes" still
                # commits, instead of silently dropping it.
                self.pending = previous
                reply = (reply or "") + ("\n(The earlier proposal is still "
                                         "open — reply yes to commit it.)")
            else:
                self.pending = decision if decision and decision.candidates else None
                self.options = list(decision.options) if decision else []
                self._add_commit_options()
            return reply or "(no reply)", self.options
        decision = self.desk.handle_message(text, requester=requester or None)
        self.pending = decision if decision.candidates else None
        self.options = list(decision.options)
        self._add_commit_options()
        return decision.explanation or "(no reply)", self.options

    def _add_commit_options(self):
        """An open proposal gets one-tap buttons: yes commits the desk's
        choice; each other candidate gets its own commit button. The tapped
        text re-enters handle() and matches the deterministic commit
        patterns in desk.confirmation (no LLM round)."""
        if self.pending is None or self.options:
            return
        others = [c for c in self.pending.candidates[:3]
                  if self.pending.chosen is None
                  or c.workshop_id != self.pending.chosen.workshop_id]
        self.options = ["yes"] + [f"commit to {c.workshop_id}"
                                  for c in others]

    def handle_option(self, token, index, requester=""):
        if token != self.options_token or not 0 <= index < len(self.options):
            return "This choice has expired. Please use the latest proposal.", []
        return self.handle(self.options[index], requester)
