"""Follow-up handling: yes-detections commit without an LLM round; the
OPTIONS line becomes tappable choices — with failure cases each."""

import pytest

from desk.contracts import Behaviour, Candidate, Decision
from desk.desk import commit_intent_workshop, extract_options, looks_like_confirmation

_CANDS = [Candidate("W6", "Nimble Needle", "2026-04-06", 0, 480.0, 0.05),
          Candidate("W2", "SteadyHands", "2026-04-08", 0, 520.0, 0.03),
          Candidate("W5", "GiantWeave", "2026-04-09", 0, 440.0, 0.06)]


def _decision(chosen="W6"):
    return Decision(request_id="R07", behaviour=Behaviour.ALLOCATE,
                    candidates=list(_CANDS),
                    chosen=next(c for c in _CANDS if c.workshop_id == chosen))


# --- looks_like_confirmation -----------------------------------------------

def test_bare_yes_variants():
    for text in ("yes", "Yes.", "YES!", "ok", "commit", "go ahead",
                 "confirm", "please do", "确认", "好的"):
        assert looks_like_confirmation(text), text


def test_non_confirmations_rejected():
    for text in ("no", "not yet", "which workshop?", "yes but split it",
                 "wait", "hold on", ""):
        assert not looks_like_confirmation(text), text


# --- commit_intent_workshop --------------------------------------------------

def test_yes_commits_the_recommendation():
    assert commit_intent_workshop("yes", _decision()) == "W6"


def test_named_workshop_commits_that_candidate():
    assert commit_intent_workshop("commit to W2", _decision()) == "W2"
    assert commit_intent_workshop("send it to SteadyHands", _decision()) == "W2"


def test_question_about_a_workshop_is_conversation():
    assert commit_intent_workshop("why is W4 not listed?", _decision()) is None
    assert commit_intent_workshop("how much is GiantWeave?", _decision()) is None
    assert commit_intent_workshop("tell me more", _decision()) is None


# --- looks_like_confirmation -----------------------------------------------

def test_bare_yes_variants():
    for text in ("yes", "Yes.", "YES!", "ok", "commit", "go ahead",
                 "confirm", "please do", "确认", "好的"):
        assert looks_like_confirmation(text), text


def test_non_confirmations_rejected():
    for text in ("no", "not yet", "which workshop?", "yes but split it",
                 "wait", "hold on", ""):
        assert not looks_like_confirmation(text), text


# --- extract_options ---------------------------------------------------------

def test_options_line_split_and_stripped():
    expl = ("TrendCart has several open orders.\n"
            "OPTIONS: ORD-101 | ORD-102 | ORD-103")
    clean, opts = extract_options(expl)
    assert opts == ["ORD-101", "ORD-102", "ORD-103"]
    assert "OPTIONS" not in clean and "several open orders" in clean


def test_no_options_line_returns_text_unchanged():
    expl = "Nobody can hit Apr 04. Earliest is Apr 17 at SteadyHands."
    clean, opts = extract_options(expl)
    assert opts == [] and clean == expl


def test_empty_options_tail_dropped():
    clean, opts = extract_options("Which one?\nOPTIONS: ORD-061 |")
    assert opts == ["ORD-061"] and "OPTIONS" not in clean
