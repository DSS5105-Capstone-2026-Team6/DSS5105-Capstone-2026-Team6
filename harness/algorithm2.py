"""
algorithm2.py — EFT baselines and the lateness-first hybrid (rewritten).

Baselines (fixed, not tuned):
    eft          earliest expected finish: queue + E[work] + transport, where
                 E[work] prices the simulator's defect model (a defective batch
                 is redone at 1.5x, so E[work] = work * (1 + 0.5 * defect_rate))
    eft_reserved eft + accessory-capacity reservation for TOPS orders

Hybrid (the algorithm under test), lexicographic by the declared objective
hierarchy -- lateness first, defects second:

    1. Estimate every eligible workshop's finish with the same E[work] model
       as eft: E[finish] = queue + E[work] + transport.
    2. Lateness is the first constraint: expected days late =
       max(0, E[finish] - slack) where slack = due_date - sent_date. Keep only
       the plateau of workshops within `late_tol` days of the best achievable.
       When no workshop is expected late (best = 0), the lateness signal is
       exhausted, so the plateau is tightened to workshops within `late_tol`
       days of the earliest E[finish] -- this keeps queues short and preserves
       the slack that absorbs defect rework.
    3. Defects are the second constraint: inside the plateau pick the lowest
       defect_rate (tiebreak: E[finish], cost, then workshop_id).

`late_tol` is the single tuning knob, scanned by --scan: how many days of
extra expected lateness to accept in exchange for a lower defect rate.

Usage (from this directory):

    python algorithm2.py              # hybrid-vs-baselines tables AND the
                                         #   tolerance scan (4 scenario cells each)
    python algorithm2.py --scan-only  # only the tolerance scan tables
    python algorithm2.py --tol 3      # run the tables with late_tol = 3 days
    python algorithm2.py --seed 7 --seeds 1
"""

import argparse
from datetime import date

from simulate import (
    Simulator, eligible_workshops, average_over_seeds, print_table,
    random_choice, greedy_biggest, cheapest,
)

DAY0 = date(2026, 1, 1)  # first order_date in orders.csv


def est_turnaround_expected(batch, w, queues):
    """Expected finish under the simulator's defect model: a defective batch
    (probability defect_rate) is redone at 1.5x work, so
    E[work] = work * (1 + 0.5 * defect_rate)."""
    work = batch["pieces"] / w.capacity
    return queues[w.workshop_id] + work * (1 + 0.5 * w.defect_rate) + w.lead_days


def eft(batch, workshops, queues):
    """Earliest expected finish over eligible workshops (defect rework priced
    in, so the baseline and the hybrid share one time model)."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: est_turnaround_expected(batch, w, queues)).workshop_id


def eft_reserved(batch, workshops, queues):
    """EFT + accessory-capacity reservation: for TOPS orders, restrict to
    TOPS-only workshops if one can still meet the due date; otherwise plain EFT."""
    ok = eligible_workshops(batch, workshops)
    if batch["category"] == "TOPS":
        slack = (batch["due_date"] - batch["sent_date"]).days
        feasible = [w for w in ok
                    if w.makes == {"TOPS"}
                    and est_turnaround_expected(batch, w, queues) <= slack]
        if feasible:
            return min(feasible,
                       key=lambda w: est_turnaround_expected(batch, w, queues)).workshop_id
    return eft(batch, workshops, queues)


# ------------------------------- the hybrid -------------------------------

def expected_days_late(batch, w, queues):
    """First-constraint value: expected days past the due date."""
    slack = (batch["due_date"] - batch["sent_date"]).days
    return max(0.0, est_turnaround_expected(batch, w, queues) - slack)


def make_hybrid_allocator(late_tol):
    """Lateness-first, defects second. Keep the plateau of eligible workshops
    whose expected days late is within `late_tol` days of the best; when the
    best is 0 (nobody late), tighten the plateau to within `late_tol` days of
    the earliest expected finish so queues stay short. Inside the plateau pick
    the lowest defect_rate (tiebreak: E[finish], cost, workshop_id)."""
    def hybrid(batch, workshops, queues):
        ok = eligible_workshops(batch, workshops)
        late = {w.workshop_id: expected_days_late(batch, w, queues) for w in ok}
        best = min(late.values())
        plateau = [w for w in ok if late[w.workshop_id] <= best + late_tol]
        if best == 0.0:
            finish = {w.workshop_id: est_turnaround_expected(batch, w, queues)
                      for w in plateau}
            earliest = min(finish.values())
            plateau = [w for w in plateau
                       if finish[w.workshop_id] <= earliest + late_tol]
        return min(plateau,
                   key=lambda w: (w.defect_rate,
                                  est_turnaround_expected(batch, w, queues),
                                  batch["pieces"] * w.cost,
                                  w.workshop_id)).workshop_id

    return hybrid


# ------------------------------- tables -------------------------------

BASELINES = {
    "random": random_choice,
    "greedy_biggest": greedy_biggest,
    "cheapest": cheapest,
    "eft": eft,
    "eft_reserved": eft_reserved,
}


def hybrid_table(seed, n_seeds, tol, stages=False, shock=False):
    """The hybrid at one tolerance against the fixed baselines, full metrics."""
    seeds = range(seed, seed + n_seeds)
    allocators = {**BASELINES, f"hybrid(tol={tol:g})": make_hybrid_allocator(tol)}
    rows = average_over_seeds(allocators, seeds, shock=shock, stages=stages)
    mode, variant = ("SHOCK" if shock else "NORMAL"), ("--stages" if stages else "default simulator")
    print(f"HYBRID vs BASELINES | {mode} | {variant} | seeds {seed}..{seed + n_seeds - 1}")
    print("hybrid: lateness-first on E[finish] (defect rework priced at 1.5x), "
          "then lowest defect rate within the lateness plateau")
    print_table(rows)


def scan_tolerance(seed, n_seeds, tolerances, stages=False, shock=False):
    """Scan late_tol and show the two-stage selection process, matching the
    declared objective hierarchy: stage 1 keeps only the tolerances achieving
    the best lateness (%% late, tiebreak late days); stage 2 optimises defects
    (%% def pcs) among the survivors, tiebreak cost, then smaller tolerance."""
    seeds = range(seed, seed + n_seeds)
    allocators = {f"{t:g}": make_hybrid_allocator(t) for t in tolerances}
    rows = average_over_seeds(allocators, seeds, shock=shock, stages=stages)
    mode, variant = ("SHOCK" if shock else "NORMAL"), ("--stages" if stages else "default simulator")

    def m(t):
        return rows[f"{t:g}"]

    # stage 1: lateness-first filter -- keep the tolerances on the lateness plateau
    best_late = min((m(t)["% late"], m(t)["late days"]) for t in tolerances)
    plateau = [t for t in tolerances
               if (m(t)["% late"], m(t)["late days"]) == best_late]

    header = (f"{'late_tol':>9}{'% late':>8}{'late days':>11}{'% def pcs':>10}"
              f"{'cost ($)':>12}{'max share':>11}{'  stage 1':>10}{'  stage 2':>10}")
    print(f"TOLERANCE SCAN | {mode} | {variant} | seeds {seed}..{seed + n_seeds - 1}")
    print("stage 1 (lateness first): keep tol with min (% late, late days) -- marked keep")
    print("stage 2 (defects second): among the keepers, min % def pcs "
          "(tiebreak cost, smaller tol) -- marked PICK")
    print(header)
    print("-" * len(header))

    # stage 2: defect optimisation inside the lateness plateau
    chosen = min(plateau,
                 key=lambda t: (m(t)["% def pcs"], m(t)["cost"], t))

    for t in tolerances:
        r = m(t)
        s1 = "keep" if t in plateau else "drop"
        s2 = "PICK" if t == chosen else ("candidate" if t in plateau else "-")
        print(f"{t:>9.1f}{r['% late']:>7.1f}%{r['late days']:>11.2f}"
              f"{r['% def pcs']:>9.1f}%{r['cost']:>12,.0f}{r['max share']:>10.0f}%"
              f"{s1:>10}{s2:>12}")
    print(f"=> stage 1 plateau: {len(plateau)}/{len(tolerances)} tolerances at "
          f"% late {best_late[0]:.1f}, late days {best_late[1]:.2f}")
    print(f"=> selected late_tol = {chosen:g} "
          f"(% def pcs {m(chosen)['% def pcs']:.1f}, cost {m(chosen)['cost']:,.0f})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--seeds", type=int, default=10, metavar="N",
                        help="average over N seeds starting at --seed (default 10)")
    parser.add_argument("--tol", type=float, default=0.5,
                        help="hybrid lateness-plateau half-width in days (default 0.5, "
                             "the value --scan selects: % late is flat at 0-0.5 and "
                             "worsens beyond it)")
    parser.add_argument("--scan-only", action="store_true",
                        help="print only the tolerance scan tables, skip the "
                             "hybrid-vs-baselines tables")
    args = parser.parse_args()

    tolerances = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0)

    if not args.scan_only:
        for shock in (False, True):
            for stages in (False, True):
                hybrid_table(args.seed, args.seeds, args.tol, stages=stages, shock=shock)
                print()

    for stages in (False, True):
        for shock in (False, True):
            scan_tolerance(args.seed, args.seeds, tolerances, stages=stages, shock=shock)
            print()
