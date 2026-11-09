from datetime import date, timedelta
from math import floor
from random import Random


def finish_production(
    day0, start_day, work_days, workshop_id, *,
    sunday_closed=False, noise_pct=0, seed=5105,
):
    """Return the production finish offset and Sunday pause in days."""
    if not 0 <= noise_pct <= 50:
        raise ValueError("noise_pct must be between 0 and 50")

    day = start_day
    remaining = work_days
    pause = 0.0
    spread = noise_pct / 100

    while remaining > 1e-9:
        day_index = floor(day)
        current = day0 + timedelta(days=day_index)
        next_day = day_index + 1
        available = next_day - day

        if sunday_closed and current.weekday() == 6:
            pause += available
        else:
            key = f"{seed}|{workshop_id}|{current.isoformat()}"
            rate = 1 + Random(key).uniform(-spread, spread)
            completed = available * rate

            if remaining <= completed:
                return day + remaining / rate, pause

            remaining -= completed

        day = next_day

    return day, pause


if __name__ == "__main__":
    print(finish_production(date(2026, 1, 3), 0, 2, "W6", sunday_closed=True))