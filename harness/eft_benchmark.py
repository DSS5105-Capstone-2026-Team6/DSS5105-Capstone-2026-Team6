"""
eft_benchmark.py — the EFT benchmark and hybrid weight sweep (Sprint 1 roadmap).

EFT ("earliest estimated finish") picks the eligible workshop with the smallest
queue + pieces/capacity + transport days. eft_reserved keeps TOPS orders off
the accessory shops when a TOPS-only shop still meets the date. The hybrid
allocator adds defect and cost terms; --grid scans the raw weights on the
simplex w_late + w_defect + w_cost = 1 and selects lateness-first, then defects.

Usage (from this directory):

    python eft_benchmark.py             # NORMAL/SHOCK x (weight sweep default,
                                        #   weight sweep --stages, baselines)
    python eft_benchmark.py --grid      # weight scan (step 0.01), select
                                        #   lateness-first then defects
    python eft_benchmark.py --seed 7 --seeds 1
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


def make_weighted_allocator(w_late, w_defect, w_cost):
    """score = w_late*est_finish + w_defect*defect_rate + w_cost*cost, each
    component min-max scaled to 0-1 across the batch's eligible candidates.
    (1, 0, 0) is plain EFT. Deterministic, no LLM."""
    def weighted(batch, workshops, queues):
        ok = eligible_workshops(batch, workshops)
        parts = (
            ({w.workshop_id: est_turnaround(batch, w, queues) for w in ok}, w_late),
            ({w.workshop_id: w.defect_rate for w in ok}, w_defect),
            ({w.workshop_id: batch["pieces"] * w.cost for w in ok}, w_cost),
        )
        score = {}
        for component, weight in parts:
            for k, v in _scaled(component).items():
                score[k] = score.get(k, 0.0) + weight * v
        return min(score, key=lambda wid: (score[wid], wid))

    return weighted


def make_hybrid_allocator(w):
    """score = w * est_finish + (1-w) * [0.75 * defect + 0.25 * cost], each
    component scaled 0-1. w = 1.0 is plain EFT."""
    return make_weighted_allocator(w, 0.75 * (1 - w), 0.25 * (1 - w))


# ------------------------------- tables -------------------------------

BASELINES = {
    "random": random_choice,
    "greedy_biggest": greedy_biggest,
    "cheapest": cheapest,
    "eft": eft,
    "eft_reserved": eft_reserved,
}


def sweep_table(seed, n_seeds, stages=False, shock=False,
                weights=(1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4)):
    """Finish-weight sweep (0.75/0.25 defect-cost split) for one scenario/variant."""
    seeds = range(seed, seed + n_seeds)
    rows = average_over_seeds(
        {f"w={w}": make_hybrid_allocator(w) for w in weights},
        seeds, shock=shock, stages=stages)
    mode, variant = ("SHOCK" if shock else "NORMAL"), ("--stages" if stages else "default simulator")
    header = (f"{'w':>6}{'% late':>8}{'late days':>11}{'% def pcs':>10}"
              f"{'cost ($)':>12}{'max share':>11}")
    print(f"WEIGHT SWEEP | {mode} | {variant} | seeds {seed}..{seed + n_seeds - 1}")
    print("score = w x est.finish + (1-w) x [0.75 x defect + 0.25 x cost], each scaled 0-1")
    print(header)
    print("-" * len(header))
    for w in weights:
        m = rows[f"w={w}"]
        print(f"{w:>6.1f}{m['% late']:>7.0f}%{m['late days']:>11.1f}"
              f"{m['% def pcs']:>9.0f}%{m['cost']:>12,.0f}{m['max share']:>10.0f}%")


def combined_table(seed, n_seeds, shock=False):
    """Baseline comparison, both variants side by side."""
    seeds = range(seed, seed + n_seeds)
    default = average_over_seeds(BASELINES, seeds, shock=shock, stages=False)
    stages = average_over_seeds(BASELINES, seeds, shock=shock, stages=True)
    cols = ("% late", "late days", "% def pcs", "cost")
    header = f"{'policy':<15}" + "".join(f"{c:>11}" for c in cols) * 2
    mode = "SHOCK" if shock else "NORMAL"
    print(f"BASELINES | {mode} | seeds {seed}..{seed + n_seeds - 1}   "
          f"[left: default simulator | right: --stages]")
    print(header)
    print("-" * len(header))
    for name in BASELINES:
        d, s = default[name], stages[name]
        print(f"{name:<15}" + "".join(f"{d[c]:>11.1f}" for c in cols)
              + "".join(f"{s[c]:>11.1f}" for c in cols))


def grid_search(seed, n_seeds, step=0.01, stages=False, shock=False,
                late_tol=0.5, target=(0.6, 0.3, 0.1)):
    """Scan the raw weights (w_late, w_defect, w_cost = 1 - w_late - w_defect)
    on a simplex grid. Selection is lexicographic, matching the declared
    objective hierarchy: first scan lateness -- keep only grid points whose
    % late is within late_tol of the grid minimum -- then optimise defects,
    tiebreak cost, then higher w_late."""
    n = int(round(1 / step))
    axis = [round(i * step, 2) for i in range(n + 1)]
    combos = [(wl, wd) for wl in axis for wd in axis if wl + wd <= 1.0 + 1e-9]

    def key(wl, wd):
        return f"{wl:.2f},{wd:.2f}"

    rows = average_over_seeds(
        {key(wl, wd): make_weighted_allocator(wl, wd, round(1 - wl - wd, 2))
         for wl, wd in combos},
        range(seed, seed + n_seeds), shock=shock, stages=stages)

    def cell(wl, wd, metric):
        return rows[key(wl, wd)][metric]

    mode, variant = ("SHOCK" if shock else "NORMAL"), ("--stages" if stages else "default simulator")
    print(f"WEIGHT SCAN | {mode} | {variant} | {len(combos)} combos (step {step}) "
          f"x {n_seeds} seeds ({seed}..{seed + n_seeds - 1})")

    # stage 1: scan lateness -- best achievable % late at each w_late
    best_late = min(rows[k]["% late"] for k in rows)
    print(f"stage 1, lateness scan (grid min {best_late:.1f}%; "
          f"plateau = within {late_tol:.1f}pp, marked *):")
    print(f"{'w_late':>7}{'min % late':>11}")
    for wl in axis:
        m = min(cell(wl, wd, "% late") for wd in axis if wl + wd <= 1.0 + 1e-9)
        mark = " *" if m <= best_late + late_tol else ""
        print(f"{wl:>7.2f}{m:>10.1f}%{mark}")

    # stage 2: among the plateau, optimise defects
    feasible = [(wl, wd) for wl, wd in combos if cell(wl, wd, "% late") <= best_late + late_tol]
    feasible.sort(key=lambda c: (cell(*c, "% def pcs"), cell(*c, "cost"), -c[0]))
    print(f"stage 2, defect optimisation within the plateau ({len(feasible)} points):")
    for wl, wd in feasible[:5]:
        m = rows[key(wl, wd)]
        print(f"  ({wl:.2f}, {wd:.2f}, {1 - wl - wd:.2f})  % late {m['% late']:.1f}  "
              f"late days {m['late days']:.1f}  % def pcs {m['% def pcs']:.1f}  "
              f"cost {m['cost']:,.0f}  max share {m['max share']:.0f}%")

    twl, twd, twc = target
    if twl in axis and twd in axis and abs(twl + twd + twc - 1) < 1e-9:
        m = rows[key(twl, twd)]
        rank = next((i + 1 for i, c in enumerate(feasible) if c == (twl, twd)), None)
        late_rank = 1 + sum(1 for c in combos if cell(*c, "% late") < m["% late"])
        print(f"declared hybrid {target}: % late {m['% late']:.1f} "
              f"(rank {late_rank}/{len(combos)} by lateness), % def pcs {m['% def pcs']:.1f}, "
              f"cost {m['cost']:,.0f}; selection-rule rank "
              f"{'#%d of %d' % (rank, len(feasible)) if rank else 'infeasible'}")
    wl, wd = feasible[0]
    print(f"=> selected: ({wl:.2f}, {wd:.2f}, {1 - wl - wd:.2f})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--seeds", type=int, default=10, metavar="N",
                        help="average over N seeds starting at --seed (default 10)")
    parser.add_argument("--grid", action="store_true",
                        help="scan the raw weights on a simplex grid, lateness-first "
                             "then defects; skips the other tables")
    parser.add_argument("--step", type=float, default=0.01, help="grid step (default 0.01)")
    parser.add_argument("--late-tol", type=float, default=0.5,
                        help="plateau half-width in percentage points (default 0.5)")
    args = parser.parse_args()

    if args.grid:
        for stages in (False, True):
            for shock in (False, True):
                grid_search(args.seed, args.seeds, step=args.step, stages=stages,
                            shock=shock, late_tol=args.late_tol)
                print()
        raise SystemExit

    for shock in (False, True):
        for stages in (False, True):
            sweep_table(args.seed, args.seeds, stages=stages, shock=shock)
            print()
        combined_table(args.seed, args.seeds, shock=shock)
        print()
