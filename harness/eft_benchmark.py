"""
eft_benchmark.py — the EFT benchmark from the Sprint 1 roadmap (Section 3.1).

EFT ("earliest estimated finish") picks the eligible workshop with the smallest
queue + pieces/capacity + transport days. Its estimate is the simulator's own
turnaround formula, which is why it is the bar to beat rather than the three
shipped baselines. Also included: the accessory-capacity reservation experiment
from Table 6 (send TOPS orders to TOPS-only workshops whenever they still meet
the due date, keeping accessory shops free for scarves/beanie reorders).

Usage (from this directory):

    python eft_benchmark.py                # NORMAL and SHOCK, each with a finish-weight
                                           #   sweep, a defect-share sweep (why d=0.75),
                                           #   and the baseline comparison
    python eft_benchmark.py --grid         # 2D scan: 10 w values x 12 d values x 10 seeds,
                                           #   pick (w, d) by the objective hierarchy
    python eft_benchmark.py --sweep        # only the two sweeps, no baselines
    python eft_benchmark.py --w 0.7        # fix another finish weight in the share sweep
    python eft_benchmark.py --seed 7 --seeds 1   # single seed for any mode
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


def make_hybrid_allocator(w, defect_share=0.75):
    """Hybrid-weighted scoring over eligible candidates:

        score = w * est_finish
              + (1-w) * [ d * defect_rate + (1-d) * cost ]

    where d = defect_share, the fraction of the non-finish weight given to
    defects (cost gets the rest). d is a PARAMETER, not a constant: 0.75 is
    our chosen value because defects is the declared second objective, and the
    split sweep table shows how the metrics move as d changes. Each component
    is min-max scaled to 0-1 across the batch's eligible candidates before
    weighting. w = 1.0 is plain EFT. Deterministic, no LLM."""
    w_finish = w
    w_defect = (1 - w) * defect_share
    w_cost = (1 - w) * (1 - defect_share)

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

    hybrid.__name__ = f"hybrid_w{w}_d{defect_share}"
    return hybrid


def combined_table(seed, n_seeds, shock=False):
    """One table, both variants side by side: every policy's headline metrics
    under the default simulator and under the stages extension."""
    seeds = range(seed, seed + n_seeds)
    allocators = {
        "random": random_choice,
        "greedy_biggest": greedy_biggest,
        "cheapest": cheapest,
        "eft": eft,
        "eft_reserved": eft_reserved,
    }
    default = average_over_seeds(allocators, seeds, shock=shock, stages=False)
    stages = average_over_seeds(allocators, seeds, shock=shock, stages=True)
    cols = ("% late", "late days", "% def pcs", "cost")
    header = f"{'policy':<15}" + "".join(f"{c:>11}" for c in cols) * 2
    mode = "SHOCK" if shock else "NORMAL"
    print(f"BASELINES | {mode} | seeds {seed}..{seed + n_seeds - 1}   "
          f"[left: default simulator | right: --stages]")
    print(header)
    print("-" * len(header))
    for name in allocators:
        d, s = default[name], stages[name]
        print(f"{name:<15}" + "".join(f"{d[c]:>11.1f}" for c in cols)
              + "".join(f"{s[c]:>11.1f}" for c in cols))


def sweep_table(seed, n_seeds, weights=(1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4),
                stages=False, shock=False, defect_share=0.75):
    """Finish-weight sweep for ONE scenario and ONE variant, at a fixed
    defect_share of the non-finish weight."""
    seeds = range(seed, seed + n_seeds)
    rows = average_over_seeds(
        {f"w={w}": make_hybrid_allocator(w, defect_share) for w in weights},
        seeds, shock=shock, stages=stages)
    mode = "SHOCK" if shock else "NORMAL"
    variant = "--stages" if stages else "default simulator"
    header = (f"{'w':>6}{'% late':>8}{'late days':>11}{'% def pcs':>10}"
              f"{'cost ($)':>12}{'max share':>11}")
    print(f"FINISH-WEIGHT SWEEP | {mode} | {variant} | seeds {seed}..{seed + n_seeds - 1}")
    print(f"score = w x est.finish + (1-w) x [{defect_share:.2f} x defect "
          f"+ {1 - defect_share:.2f} x cost], each scaled 0-1")
    print(header)
    print("-" * len(header))
    for w in weights:
        m = rows[f"w={w}"]
        print(f"{w:>6.1f}{m['% late']:>7.0f}%{m['late days']:>11.1f}"
              f"{m['% def pcs']:>9.0f}%{m['cost']:>12,.0f}{m['max share']:>10.0f}%")


def split_table(seed, n_seeds, w=0.6, shares=(0.0, 0.25, 0.5, 0.65, 0.75, 0.85, 1.0),
                stages=False, shock=False):
    """Defect-share sweep at a fixed finish weight: why 0.75? As d moves from 0
    (cost-only secondary) to 1 (defects-only secondary), watch lateness, defect
    exposure and cost trade against each other. d = 0.75 is our choice because
    defects is the declared second objective and cost is margin only."""
    seeds = range(seed, seed + n_seeds)
    rows = average_over_seeds(
        {f"d={d}": make_hybrid_allocator(w, d) for d in shares},
        seeds, shock=shock, stages=stages)
    mode = "SHOCK" if shock else "NORMAL"
    variant = "--stages" if stages else "default simulator"
    header = (f"{'d':>6}{'% late':>8}{'late days':>11}{'% def pcs':>10}"
              f"{'cost ($)':>12}{'max share':>11}")
    print(f"DEFECT-SHARE SWEEP | {mode} | {variant} | fixed w={w} | seeds {seed}..{seed + n_seeds - 1}")
    print("score = w x est.finish + (1-w) x [d x defect + (1-d) x cost], each scaled 0-1")
    print(header)
    print("-" * len(header))
    for d in shares:
        m = rows[f"d={d}"]
        print(f"{d:>6.2f}{m['% late']:>7.0f}%{m['late days']:>11.1f}"
              f"{m['% def pcs']:>9.0f}%{m['cost']:>12,.0f}{m['max share']:>10.0f}%")


def linspace(lo, hi, n):
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def grid_search(seed, n_seeds, n_w=10, n_d=12, stages=False, shock=False,
                late_tol=0.5):
    """Full 2D scan over (w, d): n_w finish weights x n_d defect shares.

    Selection rule, matching the declared objective hierarchy (lateness primary,
    defects second, cost margin only): among grid points whose % late is within
    late_tol percentage points of the grid minimum, pick the one with the lowest
    % def pcs; break ties by lower cost, then by higher w (lateness weight).
    """
    w_values = linspace(1.0, 0.4, n_w)
    d_values = linspace(0.0, 1.0, n_d)
    allocators = {f"w={w:.3f},d={d:.3f}": make_hybrid_allocator(w, d)
                  for w in w_values for d in d_values}
    rows = average_over_seeds(allocators, range(seed, seed + n_seeds),
                              shock=shock, stages=stages)
    mode = "SHOCK" if shock else "NORMAL"
    variant = "--stages" if stages else "default simulator"
    print(f"WEIGHT GRID | {mode} | {variant} | {n_w}x{n_d}={n_w * n_d} combos "
          f"x {n_seeds} seeds ({seed}..{seed + n_seeds - 1})")

    def cell(w, d, metric):
        return rows[f"w={w:.3f},d={d:.3f}"][metric]

    print(f"% late (grid min {min(cell(w, d, '% late') for w in w_values for d in d_values):.1f}):")
    print(f"{'w \\ d':>7}" + "".join(f"{d:>7.2f}" for d in d_values))
    for w in w_values:
        print(f"{w:>7.3f}" + "".join(f"{cell(w, d, '% late'):>6.0f}%" for d in d_values))
    print(f"% def pcs:")
    print(f"{'w \\ d':>7}" + "".join(f"{d:>7.2f}" for d in d_values))
    for w in w_values:
        print(f"{w:>7.3f}" + "".join(f"{cell(w, d, '% def pcs'):>6.0f}%" for d in d_values))

    best_late = min(cell(w, d, "% late") for w in w_values for d in d_values)
    feasible = [(w, d) for w in w_values for d in d_values
                if cell(w, d, "% late") <= best_late + late_tol]
    feasible.sort(key=lambda wd: (cell(*wd, "% def pcs"), cell(*wd, "cost"), -wd[0]))
    print(f"selection: % late within {late_tol:.1f}pp of grid min ({best_late:.1f}%), "
          "then minimise % def pcs, tiebreak cost, then higher w:")
    for w, d in feasible[:5]:
        m = rows[f"w={w:.3f},d={d:.3f}"]
        print(f"  w={w:.3f} d={d:.3f}  % late {m['% late']:.1f}  late days {m['late days']:.1f}  "
              f"% def pcs {m['% def pcs']:.1f}  cost {m['cost']:,.0f}  max share {m['max share']:.0f}%")
    w, d = feasible[0]
    print(f"=> chosen (w, d) = ({w:.3f}, {d:.3f})")
    return w, d


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--seeds", type=int, default=10, metavar="N",
                        help="average over N seeds starting at --seed (default 10)")
    parser.add_argument("--sweep", action="store_true",
                        help="only the weight sweeps, skip the baseline comparisons")
    parser.add_argument("--w", type=float, default=0.6,
                        help="finish weight fixed in the defect-share sweep (default 0.6)")
    parser.add_argument("--grid", action="store_true",
                        help="2D weight grid search (10 w values x 12 d values) that "
                             "derives the (w, d) combination; skips the other tables")
    args = parser.parse_args()

    if args.grid:
        for stages in (False, True):
            for shock in (False, True):
                grid_search(args.seed, args.seeds, stages=stages, shock=shock)
                print()
        raise SystemExit

    for shock in (False, True):
        for stages in (False, True):
            sweep_table(args.seed, args.seeds, stages=stages, shock=shock)
            print()
            split_table(args.seed, args.seeds, w=args.w, stages=stages, shock=shock)
            print()
        if not args.sweep:
            combined_table(args.seed, args.seeds, shock=shock)
            print()
