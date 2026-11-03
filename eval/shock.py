"""
shock — shared shock-calendar and shock-aware label tooling.

The calendar mirrors harness/simulate.py's closure model (a seeded random
ACTIVE workshop closes for a fixed window), generalised to a periodic
every-other-week schedule for the Jan-Apr timeline. build_overlay() derives
the shock-aware companion of a label file: the original labels stay
untouched, the overlay records what each expectation becomes under the
calendar.
"""

import json
import random
from datetime import date
from pathlib import Path

DEFAULT_WINDOWS = [(14, 28), (42, 56), (70, 84), (98, 112)]
DEFAULT_DAY0 = date(2026, 1, 1)


def build_calendar(active_ids, windows=DEFAULT_WINDOWS, seed=5105):
    """Seeded periodic closures: [{"start", "end", "target"}]. The same
    seeds always produce the same calendar (reproducible evaluation)."""
    calendar = []
    for i, (start, end) in enumerate(windows):
        target = random.Random(seed + i).choice(sorted(active_ids))
        calendar.append({"start": start, "end": end, "target": target})
    return calendar


def shock_on(day, calendar):
    """The closure active on a day offset from day0, or None."""
    for c in calendar:
        if c["start"] <= day < c["end"]:
            return c
    return None


def build_overlay(labels, sent_dates, calendar, day0=DEFAULT_DAY0,
                  store=None):
    """labels: list of label dicts (request_id, behaviour, workshop, ...).
    sent_dates: {request_id: ISO date} from the inbox/records.
    store: a WorkshopStore used to resolve label workshops — labels name
    shops by name ("Little Loom"), the calendar by id ("W4").
    Returns a NEW list — each row gains:
      shock_target   the workshop closed on the sent date (or None)
      expected_under_shock  label workshops minus the closed one
      affected       True when the label's expectation lost a workshop
    Nothing is auto-relabelled; rows with an empty expectation after
    filtering are flagged for manual review."""
    if store is None:
        from desk.register import WorkshopStore
        store = WorkshopStore()
    overlay = []
    for lab in labels:
        rid = lab["request_id"]
        sent = sent_dates.get(rid)
        day = (date.fromisoformat(sent) - day0).days if sent else 0
        closure = shock_on(day, calendar)
        expected = list(lab.get("workshop") or [])
        under = [w for w in expected
                 if not closure
                 or store.resolve(w) != closure["target"]]
        overlay.append({
            **lab,
            "sent_date": sent,
            "shock_target": closure["target"] if closure else None,
            "expected_under_shock": under,
            "affected": bool(closure and len(under) < len(expected)),
        })
    return overlay


def write_overlay(labels_path, sent_dates, calendar, out_path,
                  day0=DEFAULT_DAY0):
    """f_heldout.json -> f_heldout_shock.json (companion, original kept)."""
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    overlay = build_overlay(labels, sent_dates, calendar, day0)
    Path(out_path).write_text(json.dumps(overlay, ensure_ascii=False,
                                         indent=1), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    # smoke: uv run python eval/shock.py
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.register import WorkshopStore
    active = [w.workshop_id for w in WorkshopStore().workshops.values()
              if w.status == "ACTIVE"]
    for c in build_calendar(active):
        print(f"day {c['start']:>3}-{c['end']:<3} closes {c['target']}")
