"""
tests/test_telegram_adapter.py — the platform shell around DispatchDesk.

The pure half (adapter/session.py) is unit-tested with a fake desk: trigger
filter, mention stripping, reply splitting, and the confirmation gate — a
commit happens only on an explicit yes/workshop name, never on a follow-up
question. The persona tests pin the group system prompt actually loading.
"""

import pytest
from types import SimpleNamespace
from desk.desk import DispatchDesk
from desk.confirmation import FollowupIntent

from adapter.session import (ChatSession, split_reply, strip_mention,
                             wants_bot)
from desk.contracts import (AllocationRecord, Behaviour, Candidate, Decision,
                            ParsedRequest)
from desk.agent import DispatchAgent, load_system_prompt

W6 = Candidate(workshop_id="W6", name="Nimble Needle",
               estimated_finish="2026-04-06", days_late=0.0, cost=480.0,
               defect_risk=0.05)
W2 = Candidate(workshop_id="W2", name="SteadyHands",
               estimated_finish="2026-04-08", days_late=0.0, cost=520.0,
               defect_risk=0.03)


def _alloc_decision():
    return Decision(request_id="TG1", behaviour=Behaviour.ALLOCATE,
                    parsed=ParsedRequest(order_id="ORD-073", pieces=400,
                                         category="TOPS"),
                    candidates=[W6, W2], chosen=W6,
                    explanation="Nimble Needle finishes earliest. "
                                "Reply yes to commit ORD-073 to W6.")


class FakeDesk:
    """Duck-typed DispatchDesk: canned decision, records confirms."""

    def __init__(self, decision=None):
        self.decision = decision
        self.commits = []
        self.messages = []
        self.agent = SimpleNamespace(classify_followup=lambda *args: FollowupIntent("question"))

    follow_up = DispatchDesk.follow_up

    def handle_message(self, text, requester=None):
        self.messages.append((text, requester))
        return self.decision or Decision(request_id="TG", behaviour=Behaviour.ASK,
                                         explanation="Which order?")

    def confirm(self, decision, committed_by="group"):
        self.commits.append((decision.chosen.workshop_id, committed_by))
        return AllocationRecord(record_id="A-0001",
                                decision_id=decision.request_id,
                                order_id=decision.parsed.order_id,
                                workshop_id=decision.chosen.workshop_id,
                                pieces=decision.parsed.pieces or 0,
                                committed_by=committed_by,
                                committed_at="2026-04-01T09:00:00")


def make_session(fake=None):
    fake = fake or FakeDesk(decision=_alloc_decision())
    return ChatSession(lambda: fake), fake


# ---------------- trigger filter ----------------

def test_wants_bot_private_chat_always():
    assert wants_bot("ORD-063 to W6", private=True) is True

def test_wants_bot_group_requires_mention():
    assert wants_bot("@dispatch_bot ORD-063 to W6", private=False,
                     bot_username="dispatch_bot") is True
    # failure case: group chatter without @mention must not trigger the agent
    assert wants_bot("lunch anyone?", private=False,
                     bot_username="dispatch_bot") is False

def test_wants_bot_empty_or_no_username():
    assert wants_bot("   ", private=True) is False
    assert wants_bot("ORD-063", private=False, bot_username="") is False

def test_strip_mention_leaves_request():
    assert strip_mention("@dispatch_bot ORD-063 to W6",
                         "dispatch_bot") == "ORD-063 to W6"

# ---------------- reply splitting ----------------

def test_split_reply_short_is_single_chunk():
    assert split_reply("hello") == ["hello"]
    assert split_reply("") == []

def test_split_reply_splits_at_newline_under_limit():
    long = ("x" * 100 + "\n") * 100   # ~10k chars
    parts = split_reply(long)
    assert len(parts) > 1
    assert all(len(p) <= 4096 for p in parts)
    assert "".join(p + "\n" for p in parts[:-1]) + parts[-1] == long

def test_split_reply_hard_limit_when_no_newline():
    # failure case: no newline anywhere -> cut at the byte limit, not beyond
    parts = split_reply("y" * 9000)
    assert parts == ["y" * 4096, "y" * 4096, "y" * 808]

# ---------------- confirmation gate ----------------

def test_yes_commits_recommendation_and_clears_pending():
    session, fake = make_session()
    reply, _ = session.handle("ORD-073 to Nimble Needle please", "Ravi")
    assert "Reply yes" in reply
    reply, _ = session.handle("yes", "Priya")
    assert "Committed A-0001 — ORD-073 → W6" in reply
    assert fake.commits == [("W6", "Priya")]
    assert session.pending is None

def test_naming_a_workshop_commits_that_one_not_the_star():
    session, fake = make_session()
    session.handle("ORD-073 please", "Ravi")
    reply, _ = session.handle("commit to SteadyHands", "Priya")
    assert "→ W2" in reply
    assert fake.commits == [("W2", "Priya")]

def test_followup_question_does_not_commit():
    # failure case: a question is conversation, not a confirmation — the
    # pending decision survives so a later "yes" still commits
    session, fake = make_session()
    session.handle("ORD-073 please", "Ravi")
    session.handle("but what about the defect rate?", "Priya")
    assert fake.commits == []
    assert session.pending is not None
    session.handle("yes", "Priya")
    assert fake.commits == [("W6", "Priya")]

def test_new_request_replaces_pending():
    session, fake = make_session()
    session.handle("first order", "Ravi")
    session.handle("actually, second order ORD-099", "Ravi")
    assert "actually, second order ORD-099" in fake.messages[-1][0]

def test_no_candidates_nothing_pending():
    session, _ = make_session(FakeDesk(decision=None))
    reply, _ = session.handle("which order did you mean?", "Ravi")
    assert reply == "Which order?"
    assert session.pending is None

# ---------------- persona ----------------

def test_group_persona_loads_and_differs_from_dispatcher():
    group = load_system_prompt("group")
    assert group != load_system_prompt("dispatcher")
    assert "group chat" in group
    assert "Never commit an allocation on your own initiative" in group

def test_unknown_persona_fails_loudly():
    with pytest.raises(FileNotFoundError):
        load_system_prompt("nonexistent-persona")

def test_agent_accepts_persona_kwarg():
    agent = DispatchAgent(api_key="dummy", persona="group")
    assert agent.system_prompt == load_system_prompt("group")
