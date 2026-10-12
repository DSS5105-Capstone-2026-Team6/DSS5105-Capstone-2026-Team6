"""
eft_benchmark.py — the EFT benchmark from the Sprint 1 roadmap (Section 3.1).

EFT ("earliest estimated finish") picks the eligible workshop with the smallest
queue + pieces/capacity + transport days. Its estimate is the simulator's own
turnaround formula, which is why it is the bar to beat rather than the three
shipped baselines. Also included: the accessory-capacity reservation experiment
from Table 6 (send TOPS orders to TOPS-only workshops whenever they still meet
the due date, keeping accessory shops free for scarves/beanie reorders).

Usage (from this directory):

    python eft_benchmark.py                # default run, 10 seeds, normal + shock
    python eft_benchmark.py --seeds 10 --seed 5105
"""

import argparse
from datetime import date

from simulate import (
    Simulator, eligible_workshops, average_over_seeds, print_table,
    random_choice, greedy_biggest, cheapest,
)

DAY0 = date(2026, 1, 1)  # first order_date in orders.csv


def est_turnaround(batch, w, queues):
    """The simulator's own formula: queue + processing + transport, in days."""
    return queues[w.workshop_id] + batch["pieces"] / w.capacity + w.lead_days


def eft(batch, workshops, queues):
    """Earliest estimated finish over eligible workshops."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: est_turnaround(batch, w, queues)).workshop_id


def eft_reserved(batch, workshops, queues):
    """EFT + accessory-capacity reservation: for TOPS orders, restrict to
    TOPS-only workshops if one can still meet the due date; otherwise plain EFT."""
    ok = eligible_workshops(batch, workshops)
    if batch["category"] == "TOPS":
        tops_only = [w for w in ok if w.makes == {"TOPS"}]
        if tops_only:
            slack = (batch["due_date"] - DAY0).days - (batch["sent_date"] - DAY0).days
            feasible = [w for w in tops_only if est_turnaround(batch, w, queues) <= slack]
            if feasible:
                return min(feasible, key=lambda w: est_turnaround(batch, w, queues)).workshop_id
    return eft(batch, workshops, queues)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--seeds", type=int, metavar="N")
    args = parser.parse_args()

    allocators = {
        "random": random_choice,
        "greedy_biggest": greedy_biggest,
        "cheapest": cheapest,
        "eft": eft,
        "eft_reserved": eft_reserved,
    }

    for shock in (False, True):
        label = "SHOCK" if shock else "NORMAL"
        print(f"\n=== {label} (seeds {args.seed}..{args.seed + (args.seeds or 1) - 1}) ===")
        if args.seeds:
            rows = average_over_seeds(allocators, range(args.seed, args.seed + args.seeds), shock=shock)
        else:
            sim = Simulator(shock=shock, seed=args.seed)
            for name, fn in allocators.items():
                sim.run(fn, name)
            rows = {name: sim.metrics(out) for name, out in sim.results.items()}
        print_table(rows)
