"""
performance — the learned half of the estimator (roadmap §1.6).

The profile card (workshops.csv) is exact inside the shared simulator, but
in operation workshops drift. PerformanceStore learns from returned batches:
every observe() records promised vs actual completion for one batch, and
learned() derives a recency-weighted effective capacity / lead time plus an
80th-percentile delay for cautious estimates on tight-slack orders.

Guards from the roadmap:
- falls back to the profile card until MIN_SAMPLES batches are observed
- every update is bounded (at most MAX_STEP, scaled down further for small
  batches — a one-day-late 50-piece return barely moves the estimate, and
  even the first batch gets no free pass)
- observation history is capped at KEEP_MOST_RECENT

Storage uses the same backend as the allocation ledger: local SQLite or a
shared PostgreSQL database configured through DISPATCH_DATABASE_URL.
"""

import json
from datetime import date
from pathlib import Path

try:
    from desk.config import RESULTS_DIR
    from desk.storage import Database
except ImportError:  # run directly as a script
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import RESULTS_DIR
    from desk.storage import Database

MIN_SAMPLES = 3        # below this, estimate_delivery stays on the profile card
MAX_STEP = 0.2         # bounded update: ±20% capacity move per observation
DECAY = 0.9            # recency weight: one observation back weighs 0.9x
KEEP_MOST_RECENT = 20  # cap the stored history per workshop
RATIO_CLAMP = (0.5, 1.5)  # effective capacity never leaves this band


class PerformanceStore:
    def __init__(self, path=None):
        self.database = Database(path)
        self.path = self.database.path
        if self.database.is_postgres:
            self.database.require_tables('performance')
            return
        with self.database.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS performance "
                       "(workshop_id TEXT PRIMARY KEY, samples TEXT NOT NULL, "
                       " ratio REAL, updated_at TEXT NOT NULL)")

    # ---------------- write ----------------

    def observe(self, workshop_id, pieces, promised_date, actual_date,
                profile=None):
        """One returned batch -> one observation. Returns the recorded delay
        and the resulting learned state (or why it is not active yet).
        `profile` (the WorkshopStore record) makes the delay->capacity
        conversion proportional to the batch's work content."""
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._observe(db, workshop_id, pieces, promised_date, actual_date, profile)

    def _observe(self, db, workshop_id, pieces, promised_date, actual_date, profile):
        promised = date.fromisoformat(str(promised_date))
        actual = date.fromisoformat(str(actual_date))
        delay = (actual - promised).days
        pieces = int(pieces)
        row = self._row(workshop_id, db=db)
        samples = row[0] if row else []
        samples.append({"promised": promised.isoformat(),
                        "actual": actual.isoformat(),
                        "pieces": pieces, "delay": delay})
        samples = samples[-KEEP_MOST_RECENT:]

        # evidence strength scales with the batch's work content: a one-day
        # late return on a half-day job must not move the capacity estimate
        # the way a late ten-day job does (and the first batch gets no free
        # pass either — every update is bounded, starting from ratio 1.0)
        work_days = (pieces / profile.capacity * (1 + 0.5 * profile.defect_rate)
                     if profile is not None else 10.0)
        observed = self._observed_ratio(delay, work_days)
        ratio = row[1] if row else None
        if ratio is None:
            ratio = 1.0
        step = max(-MAX_STEP, min(MAX_STEP, observed - ratio))
        step *= min(1.0, work_days / 10.0)       # small batches move less
        ratio = round(ratio + step, 4)
        ratio = max(RATIO_CLAMP[0], min(RATIO_CLAMP[1], ratio))

        db.execute("INSERT INTO performance VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(workshop_id) DO UPDATE SET "
                   "samples=excluded.samples, ratio=excluded.ratio, "
                   "updated_at=excluded.updated_at",
                   (workshop_id, json.dumps(samples), ratio,
                    date.today().isoformat()))
        state = self.learned(workshop_id, profile=profile, _db=db) or {}
        return {"workshop_id": workshop_id, "delay_days": delay,
                "observations": len(samples),
                "active": len(samples) >= MIN_SAMPLES, **state}

    def clear(self):
        """Drop every learned observation (demo reset wipes these too, so a
        fresh world starts back on the profile cards)."""
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("DELETE FROM performance")

    # ---------------- read ----------------

    def learned(self, workshop_id, profile=None, *, _db=None):
        """The learned estimate for one workshop, or None while fewer than
        MIN_SAMPLES batches have been observed (profile card fallback).
        profile: the WorkshopStore record, used to convert the capacity
        ratio into pieces/day."""
        row = self._row(workshop_id, db=_db)
        if row is None:
            return None
        samples, ratio = row
        if len(samples) < MIN_SAMPLES or ratio is None:
            return None
        weights = [DECAY ** k for k in reversed(range(len(samples)))]
        delays = [s["delay"] for s in samples]
        wmean = sum(d * w for d, w in zip(delays, weights)) / sum(weights)
        out = {"capacity_ratio": ratio,
               "weighted_mean_delay": round(wmean, 2),
               "p80_delay": _percentile(delays, 80),
               "observations": len(samples)}
        if profile is not None:
            out["eff_capacity"] = round(profile.capacity * ratio, 2)
            out["profile_capacity"] = profile.capacity
            out["eff_lead_days"] = profile.lead_days + max(0, round(wmean))
        return out

    # ---------------- internals ----------------

    def _row(self, workshop_id, db=None):
        if db is None:
            with self.database.connect() as connection:
                return self._row(workshop_id, db=connection)
        row = db.execute("SELECT samples, ratio FROM performance "
                         "WHERE workshop_id=?", (workshop_id,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0]), row[1]

    def _samples(self, workshop_id):
        row = self._row(workshop_id)
        return row[0] if row else []

    def _ratio(self, workshop_id):
        row = self._row(workshop_id)
        return row[1] if row else None

    @staticmethod
    def _observed_ratio(delay, work_days):
        """Delay -> capacity ratio. The capacity-blame model: if the batch's
        pure work was `work_days` and it came back `delay` days late, the
        implied throughput is work / (work + delay) of the profile. Early
        batches nudge the ratio up, capped at +10%."""
        if delay > 0:
            return work_days / (work_days + delay)
        return 1.0 + min(0.1, -delay / 100.0)


def _percentile(values, pct):
    """Empirical percentile (nearest-rank), fine for small samples."""
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, round(len(ordered) * pct / 100))
    return ordered[min(rank, len(ordered)) - 1]
