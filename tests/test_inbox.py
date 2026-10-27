"""Unit tests for inbox parsing — the envelope split only; message text must
pass through verbatim (the inbox is deliberately not clean)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # allow direct script runs

from eval.run_eval import parse_inbox


def test_parses_all_30_requests():
    requests = parse_inbox()
    assert len(requests) == 30
    assert [r["request_id"] for r in requests] == [f"R{i:02d}" for i in range(1, 31)]


def test_envelope_fields():
    requests = parse_inbox()
    r07 = next(r for r in requests if r["request_id"] == "R07")
    assert r07["time"] == "08:23"
    assert r07["speaker"] == "Ravi"
    assert r07["text"].startswith("ORD-063")
    assert "R07" not in r07["text"] and "Ravi" not in r07["text"]


def test_text_is_verbatim():
    """No cleaning: punctuation, dashes and ellipses survive untouched."""
    requests = parse_inbox()
    r25 = next(r for r in requests if r["request_id"] == "R25")
    assert "…and keep it away from BudgetWorks" in r25["text"]


def test_split_chat_dump_skips_comments_and_splits_envelopes():
    """A pasted dump keeps its # header out of the messages and splits on
    envelope lines; a wrapped line re-attaches to its message."""
    from app.streamlit_app import split_chat_dump
    dump = ("# Dispatch requests — 1 April 2026 (evaluation set, do not edit)\n"
            "# kind: complete / impossible / constrained / ...\n"
            "R01 [08:15] Chen: need the usual scarves\n"
            "from Harbor Knits, asap\n"
            "R02 [08:16] Priya: any updates on the TrendCart reorder?\n")
    msgs = split_chat_dump(dump)
    assert len(msgs) == 2
    assert msgs[0].startswith("R01 [08:15] Chen:")
    assert "asap" in msgs[0]                     # wrapped line re-attached
    assert not any(m.startswith("#") for m in msgs)


def test_split_chat_dump_splits_heldout_ids():
    """Held-out lines (H01 ...) split one per message, like R lines."""
    from app.streamlit_app import split_chat_dump
    dump = ("H01 [13:05] Ravi: Can we get ORD-036 out the door?\n"
            "H02 [13:12] Boss: ORD-108 — 2000 scarves. Find someone.\n"
            "H03 [13:20] Chen: The Bright Basics scarf order needs to get moving\n")
    msgs = split_chat_dump(dump)
    assert [m[:3] for m in msgs] == ["H01", "H02", "H03"]


def test_parses_heldout_inbox():
    from desk.config import DATA_DIR
    requests = parse_inbox(DATA_DIR / "dispatch_requests_heldout.txt")
    assert [r["request_id"] for r in requests] == [f"H{i:02d}" for i in range(1, 21)]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
