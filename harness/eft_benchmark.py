"""
eft_benchmark.py — the EFT benchmark from the Sprint 1 roadmap (Section 3.1).

EFT ("earliest estimated finish") picks the eligible workshop with the smallest
queue + pieces/capacity + transport days. Its estimate is the simulator's own
turnaround formula, which is why it is the bar to beat rather than the three
shipped baselines. Also included: the accessory-capacity reservation experiment
from Table 6 (send TOPS orders to TOPS-only workshops whenever they still meet
the due date, keeping accessory shops free for scarves/beanie reorders).

Usage (from this directory):

    python eft_benchmark.py                # hybrid weight sweep, 10 seeds (appendix table)
    python eft_benchmark.py --baselines    # baseline comparison instead (Table 6)
    python eft_benchmark.py --seed 7       # single seed for either mode
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


def _scaled(values):
    """Min-max scale a {key: number} dict to 0-1. Equal values map to 0."""
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def make_hybrid_allocator(w):
    """Hybrid-weighted scoring over eligible candidates (appendix weight sweep):

        score = w * est_finish + 0.75(1-w) * defect_rate + 0.25(1-w) * cost

    each component min-max scaled to 0-1 across the batch's eligible candidates
    before weighting. w = 1.0 is plain EFT. Deterministic, no LLM."""
    w_finish, w_defect, w_cost = w, 0.75 * (1 - w), 0.25 * (1 - w)

    def hybrid(batch, workshops, queues):
        ok = eligible_workshops(batch, workshops)
        finish = {w.workshop_id: est_turnaround(batch, w, queues) for w in ok}
        defect = {w.workshop_id: w.defect_rate for w in ok}
        cost = {w.workshop_id: batch["pieces"] * w.cost for w in ok}
        score = {}
        for component, weight in ((finish, w_finish), (defect, w_defect), (cost, w_cost)):
            for k, v in _scaled(component).items():
                score[k] = score.get(k, 0.0) + weight * v
        return min(score, key=lambda wid: (score[wid], wid))

    hybrid.__name__ = f"hybrid_w{w}"
    return hybrid


def sweep_table(seed, n_seeds, weights=(1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4)):
    """Weight sweep: run each w over the seeds, normal and shock, and print the
    table in the appendix-slide format."""
    seeds = range(seed, seed + n_seeds)
    normal = average_over_seeds(
        {f"w={w}": make_hybrid_allocator(w) for w in weights}, seeds, shock=False)
    shock = average_over_seeds(
        {f"w={w}": make_hybrid_allocator(w) for w in weights}, seeds, shock=True)
    header = (f"{'w':>6}{'% late':>8}{'late days':>11}{'% def pcs':>10}"
              f"{'cost ($)':>12}{'max share':>11}{'shock % late':>13}")
    print(f"score = w x est.finish + 0.75(1-w) x defect + 0.25(1-w) x cost, each scaled 0-1")
    print(f"default simulator, mean over seeds {seed}..{seed + n_seeds - 1}")
    print(header)
    print("-" * len(header))
    for w in weights:
        name = f"w={w}"
        m, s = normal[name], shock[name]
        print(f"{w:>6.1f}{m['% late']:>7.0f}%{m['late days']:>11.1f}"
              f"{m['% def pcs']:>9.0f}%{m['cost']:>12,.0f}{m['max share']:>10.0f}%"
              f"{s['% late']:>12.0f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--seeds", type=int, default=10, metavar="N",
                        help="average over N seeds starting at --seed (default 10)")
    parser.add_argument("--baselines", action="store_true",
                        help="baseline comparison (random/greedy/cheapest/eft/eft_reserved) instead of the sweep")
    args = parser.parse_args()

    if not args.baselines:
        sweep_table(args.seed, args.seeds)
        raise SystemExit

    allocators = {
        "random": random_choice,
        "greedy_biggest": greedy_biggest,
        "cheapest": cheapest,
        "eft": eft,
        "eft_reserved": eft_reserved,
    }

    for shock in (False, True):
        label = "SHOCK" if shock else "NORMAL"
        print(f"\n=== {label} (seeds {args.seed}..{args.seed + args.seeds - 1}) ===")
        rows = average_over_seeds(allocators, range(args.seed, args.seed + args.seeds), shock=shock)
        print_table(rows)
