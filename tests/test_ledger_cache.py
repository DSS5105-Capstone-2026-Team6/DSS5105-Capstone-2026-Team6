"""Version-gated ledger cache: one full read per ledger version, one cheap
version query per call — and a write always shows through."""

from types import SimpleNamespace

import app.components.ledger_cache as lc


class FakeAudit:
    def __init__(self, version="v1", records=()):
        self.version = version
        self.records = list(records)
        self.full_reads = 0

    def load_all(self):
        self.full_reads += 1
        return list(self.records)


def _fake_st(monkeypatch):
    monkeypatch.setattr(lc, "st", SimpleNamespace(session_state={}))


def test_cache_reloads_only_on_version_change(monkeypatch):
    _fake_st(monkeypatch)
    audit = FakeAudit(records=["r1"])
    desk = SimpleNamespace(audit=audit)
    assert lc.ledger_records(desk) == ["r1"]     # first call: full read
    assert lc.ledger_records(desk) == ["r1"]     # same version: cached
    audit.version = "v2"                          # a commit bumps the version
    audit.records = ["r1", "r2"]
    assert lc.ledger_records(desk) == ["r1", "r2"]  # stale cache reloads
    assert audit.full_reads == 2                  # 3 calls, 2 versions


def test_cache_miss_on_first_call(monkeypatch):
    _fake_st(monkeypatch)
    audit = FakeAudit(records=["r1"])
    assert lc.ledger_records(SimpleNamespace(audit=audit)) == ["r1"]
    assert audit.full_reads == 1


def test_different_sessions_have_independent_caches(monkeypatch):
    """Two browser sessions must not share a stale copy across a commit."""
    audit = FakeAudit(records=["r1"])
    desk = SimpleNamespace(audit=audit)
    s1, s2 = {}, {}
    monkeypatch.setattr(lc, "st", SimpleNamespace(session_state=s1))
    assert lc.ledger_records(desk) == ["r1"]
    audit.version = "v2"
    audit.records = ["r1", "r2"]
    # session 1 still sees its cached copy until it re-checks the version;
    # its next call does re-check, so it reloads
    assert lc.ledger_records(desk) == ["r1", "r2"]
    monkeypatch.setattr(lc, "st", SimpleNamespace(session_state=s2))
    assert lc.ledger_records(desk) == ["r1", "r2"]
    assert audit.full_reads == 3
