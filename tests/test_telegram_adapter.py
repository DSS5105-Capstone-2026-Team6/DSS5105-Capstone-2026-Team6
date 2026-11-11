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


# ---------------- bot UX hardening ----------------

def test_yes_without_pending_gets_a_plain_answer_no_llm():
    # failure case: after a bot restart the pending proposal is gone; a bare
    # "yes" must not burn an LLM round on an empty conversation
    session, fake = make_session(FakeDesk(decision=None))
    reply, options = session.handle("yes", "Ravi")
    assert "Nothing is awaiting confirmation" in reply
    assert fake.messages == []          # the agent was never called
    assert options == []


def test_answer_without_rerank_keeps_proposal_open():
    # a follow-up the model answers without calling tools used to drop the
    # pending proposal silently; it must survive so a later yes still commits
    session, fake = make_session()
    session.handle("ORD-073 please", "Ravi")

    class AnsweringDesk(FakeDesk):
        def follow_up(self, text, decision, requester="group"):
            if "defect" in text:
                # model answered without re-ranking: no commit, no new proposal
                return None, None, "Defect risk comes from the workshop profile card."
            return DispatchDesk.follow_up(self, text, decision, requester)

    session2 = ChatSession(lambda: AnsweringDesk(_alloc_decision()))
    session2.handle("ORD-073 please", "Ravi")
    reply, _ = session2.handle("what is the defect risk?", "Priya")
    assert "still open" in reply
    reply, _ = session2.handle("yes", "Priya")
    assert "Committed A-0001" in reply


def test_cancel_clears_pending_for_good():
    # failure case for the keep-open rule: a real cancel must clear it
    session, fake = make_session()
    session.handle("ORD-073 please", "Ravi")
    reply, _ = session.handle("cancel", "Priya")
    assert "Cancelled" in reply
    assert session.pending is None
    reply, _ = session.handle("yes", "Priya")
    assert "Nothing is awaiting confirmation" in reply
    assert fake.commits == []


def test_proposal_offers_commit_buttons():
    session, _ = make_session()
    reply, options = session.handle("ORD-073 please", "Ravi")
    assert options[0] == "yes"
    # the non-chosen candidate gets its own one-tap commit button
    assert "commit to W2" in options


def test_commit_button_text_commits_via_fast_path():
    session, fake = make_session()
    session.handle("ORD-073 please", "Ravi")
    token = session.options_token
    idx = session.options.index("commit to W2")
    reply, _ = session.handle_option(token, idx, "Priya")
    assert "→ W2" in reply
    assert fake.commits == [("W2", "Priya")]


def test_queue_chart_png_renders():
    from types import SimpleNamespace
    from adapter.charts import queue_chart_png
    queues = {"W1": 2.5, "W2": 0.0, "W3": 5.1}
    shops = {w: SimpleNamespace(name=f"Shop {w}") for w in queues}
    png = queue_chart_png(queues, shops)
    assert png.read(8) == b"\x89PNG\r\n\x1a\n"


def test_queue_chart_png_handles_empty():
    from adapter.charts import queue_chart_png
    png = queue_chart_png({}, {})
    assert png.read(8) == b"\x89PNG\r\n\x1a\n"


def test_queue_text_lists_every_workshop_without_matplotlib():
    from types import SimpleNamespace
    from adapter.charts import queue_text
    queues = {"W2": 2.5, "W1": 4.0}
    shops = {"W1": SimpleNamespace(name="QuickStitch"),
             "W2": SimpleNamespace(name="SteadyHands")}
    text = queue_text(queues, shops)
    assert text.splitlines() == ["Live queues · total 6.5 days",
                                 "W1 QuickStitch: 4.0 d",
                                 "W2 SteadyHands: 2.5 d"]


def test_try_queue_chart_returns_none_when_drawing_fails(monkeypatch):
    import adapter.charts as charts

    def boom(*a, **k):
        raise ModuleNotFoundError("No module named 'matplotlib'")
    monkeypatch.setattr(charts, "queue_chart_png", boom)
    assert charts.try_queue_chart({"W1": 1.0}, {}) is None


# ---------------- batch confirm ("yes all") ----------------

def _second_decision():
    return Decision(request_id="TG2", behaviour=Behaviour.ALLOCATE,
                    parsed=ParsedRequest(order_id="ORD-045", pieces=600,
                                         category="TOPS"),
                    candidates=[W2], chosen=W2,
                    explanation="SteadyHands is free. Reply yes to commit.")


class TwoOrderDesk(FakeDesk):
    """First request proposes ORD-073, a different order follows up and
    proposes ORD-045 (the ORD-073 proposal stays open)."""
    confirm_all = DispatchDesk.confirm_all

    def handle_message(self, text, requester=None):
        self.messages.append((text, requester))
        return _alloc_decision() if "073" in text else _second_decision()

    def follow_up(self, text, decision, requester="group"):
        # a new order line is not a follow-up to the pending proposal
        if "045" in text:
            return _second_decision(), None, _second_decision().explanation
        return DispatchDesk.follow_up(self, text, decision, requester)


def test_yes_all_commits_every_open_proposal():
    session = ChatSession(lambda: TwoOrderDesk())
    fake = session.desk
    session.handle("ORD-073 please", "Ravi")
    session.handle("ORD-045 please", "Priya")
    assert len(session.pending_all) == 2
    reply, _ = session.handle("yes all", "Ravi")
    assert "ORD-073" in reply and "ORD-045" in reply
    assert sorted(fake.commits) == [("W2", "Ravi"), ("W6", "Ravi")]
    assert session.pending_all == [] and session.pending is None


def test_yes_all_without_pending_gets_a_plain_answer_no_llm():
    # failure case: nothing open -> deterministic reply, agent never called
    session, fake = make_session(FakeDesk(decision=None))
    reply, _ = session.handle("全部确认", "Ravi")
    assert "Nothing is awaiting confirmation" in reply
    assert fake.messages == []


def test_single_yes_still_commits_only_the_latest():
    # the per-order flow is unchanged: yes commits the active proposal,
    # the other open one stays for later
    session = ChatSession(lambda: TwoOrderDesk())
    fake = session.desk
    session.handle("ORD-073 please", "Ravi")
    session.handle("ORD-045 please", "Priya")
    reply, _ = session.handle("yes", "Priya")
    assert "ORD-045" in reply
    assert fake.commits == [("W2", "Priya")]
    assert [d.parsed.order_id for d in session.pending_all] == ["ORD-073"]
