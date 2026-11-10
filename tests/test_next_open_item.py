"""After a commit: nearest open order below first, else nearest above."""

from types import SimpleNamespace

from app.tabs.desk.worklist import next_open_item


def _items(n):
    return [{"decision": SimpleNamespace(n=i)} for i in range(n)]


def test_prefers_nearest_open_below():
    xs = _items(5)
    done = {id(xs[2]["decision"]), id(xs[3]["decision"])}
    nxt = next_open_item(xs, id(xs[2]["decision"]), lambda d: id(d) in done)
    assert nxt is xs[4]


def test_falls_back_to_nearest_open_above():
    xs = _items(5)
    done = {id(xs[i]["decision"]) for i in (1, 3, 4)}   # 0 and 2 skipped earlier
    nxt = next_open_item(xs, id(xs[4]["decision"]), lambda d: id(d) in done)
    assert nxt is xs[2]


def test_none_when_everything_is_committed():
    xs = _items(3)
    assert next_open_item(xs, id(xs[1]["decision"]), lambda d: True) is None
