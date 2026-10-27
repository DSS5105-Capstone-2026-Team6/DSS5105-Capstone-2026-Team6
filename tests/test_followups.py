"""Follow-up handling: yes-detections commit without an LLM round; the
OPTIONS line becomes tappable choices — with failure cases each."""

import pytest

from desk.desk import extract_options, looks_like_confirmation


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
