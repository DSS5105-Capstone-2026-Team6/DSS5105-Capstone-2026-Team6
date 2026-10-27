"""Unit tests for desk/chat_dump.py — the shared pasted-chat splitter.

The H-series bug: H01 envelopes (held-out inbox) were merged into one giant
blob because the old splitter only knew R-series ids. Bare chat lines
("Priya: ...", "[09:18] Priya: ...") must also dispatch — the dispatcher
pastes raw chat too."""

from desk.chat_dump import BARE_LINE, ENVELOPE, split_chat_dump

DUMP = ("# header comment\n"
        "H01 [09:00] Priya: send ORD-101 to W2\n"
        "H02 [09:05] Ravi: can W6 take ORD-061?\n")


def test_h_series_lines_are_split_not_merged():
    """The reported bug: H-prefixed lines used to glue into one blob."""
    msgs = split_chat_dump(DUMP)
    assert len(msgs) == 2
    assert msgs[0].startswith("H01")
    assert msgs[1].startswith("H02")


def test_envelope_accepts_r_and_h_ids():
    assert ENVELOPE.match("R07 [08:23] Ravi: hi").group(1) == "R07"
    assert ENVELOPE.match("H07 [08:23] Ravi: hi").group(1) == "H07"
    # any single capital letter + digits is a valid series; the shape still
    # has to be a full envelope, not a bare id
    assert ENVELOPE.match("R07 hi") is None


def test_bare_chat_lines_each_become_a_message():
    """Un-numbered raw chat: every 'Name: text' line dispatches on its own."""
    dump = ("Priya: Send ORD-073 to FreshStart\n"
            "[09:18] Chen: what's the queue at W1?\n")
    msgs = split_chat_dump(dump)
    assert len(msgs) == 2
    assert msgs[0].startswith("Priya:")


def test_continuation_line_joins_previous_message():
    dump = ("R01 [08:15] Chen: need the usual scarves\n"
            "from Harbor Knits, asap\n")
    msgs = split_chat_dump(dump)
    assert len(msgs) == 1
    assert "asap" in msgs[0]


def test_comments_blanks_and_empty_input():
    # failure case: nothing but noise -> no phantom messages
    assert split_chat_dump("# only a comment\n\n") == []
    assert split_chat_dump("") == []
    assert split_chat_dump(None) == []


def test_single_blob_without_structure_comes_back_verbatim():
    assert split_chat_dump("just one free-form sentence") == \
        ["just one free-form sentence"]


def test_bare_line_requires_colon_prefix():
    # failure case: a wrapped fragment like "make Apr 29" must NOT start a
    # new message — it continues the line above
    assert BARE_LINE.match("make Apr 29") is None
