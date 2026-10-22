"""Unit tests for inbox parsing — the envelope split only; message text must
pass through verbatim (the inbox is deliberately not clean)."""

from agent.inbox import parse_inbox


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
