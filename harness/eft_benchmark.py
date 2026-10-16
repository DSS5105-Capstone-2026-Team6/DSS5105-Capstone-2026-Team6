"""
eft_benchmark.py — Sprint 1 reproduction: EFT baselines + hybrid weight sweep.

Objective hierarchy (Sprint 1 review):
    1. Lateness  (% late, late days) -- the problem today; the industry runs
       on speed, quick-response reorders are due in 1-2 weeks.
    2. Defects   (% def pcs) -- also reported.
The objective is a *setting*: switch lateness / defects / hybrid without
changing the allocator.

The hybrid scores each eligible workshop
    score = w * est.finish + (1-w) * [share * defect_rate + (1-share) * cost]
with every component min-max scaled to 0-1 across the batch's eligible
candidates. Tuning is TWO-STAGE, in the objective hierarchy:

    Stage 1 -- lock w on lateness: sweep the finish-time weight w on a 0.1
        grid and take the LOWEST w whose late orders do not exceed EFT's
        (w = 1.0). Lateness is the only criterion here. On the Sprint 1 data
        (default simulator, seeds 5105-5114) that locks w = 0.7: same 2.0
        late orders as EFT at 3.4% lower cost.
    Stage 2 -- scan the defect:cost split at the locked w: keep only splits
        that still match EFT on late orders (the lateness guardrail), then
        pick the lowest % def pcs (tiebreak cost). That selects 3:1
        (def pcs 6.850 < 4:1's 6.914 < 3:2's 6.968; 1:1, defects-only and
        cost-only break the guardrail). Sprint 1: the choice is not
        sensitive between 3:2 and 3:1.

Known limits (Sprint 1): scoring the current order's days late gives 17-27%
late; defects-only scoring gives ~95% late. With stage checks and shock,
every hybrid weight adds 0.3-0.6 late orders per run versus EFT.

Usage (from this directory):

    python eft_benchmark.py                 # sweep + split check + baselines
    python eft_benchmark.py --seeds 20      # 20-seed check (Sprint 1 uses it
                                            #   for the w=0.7 confirmation)
    python eft_benchmark.py --stages        # stage-capability variant
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
    """Earliest estimated finish over eligible workshops. w = 1.0 hybrid."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: est_turnaround(batch, w, queues)).workshop_id


def eft_reserved(batch, workshops, queues):
    """EFT + accessory-capacity reservation: for TOPS orders, restrict to
    TOPS-only workshops if one can still meet the due date; otherwise plain EFT."""
    ok = eligible_workshops(batch, workshops)
    if batch["category"] == "TOPS":
        slack = (batch["due_date"] - batch["sent_date"]).days
        feasible = [w for w in ok
                    if w.makes == {"TOPS"} and est_turnaround(batch, w, queues) <= slack]
        if feasible:
            return min(feasible, key=lambda w: est_turnaround(batch, w, queues)).workshop_id
    return eft(batch, workshops, queues)


def defects_only(batch, workshops, queues):
    """Lowest defect rate, nothing else. The guardrail failure case (~95% late)."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: (w.defect_rate, w.workshop_id)).workshop_id


# ------------------------------- the hybrid -------------------------------

def _scaled(values):
    """Min-max scale a {key: number} dict to 0-1. Equal values map to 0."""
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def make_weighted_allocator(w_late, w_defect, w_cost):
    """score = w_late*est.finish + w_defect*defect_rate + w_cost*cost, each
    component min-max scaled to 0-1 across the batch's eligible candidates."""
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


def make_hybrid_allocator(w, defect_share=0.75):
    """score = w * est.finish + (1-w) * [defect_share * defect +
    (1-defect_share) * cost], each component scaled 0-1. w = 1.0 is EFT.
    defect_share = 0.75 is the Sprint 1 choice (defect : cost = 3 : 1)."""
    return make_weighted_allocator(w, defect_share * (1 - w),
                                   (1 - defect_share) * (1 - w))


# ------------------------------- tables -------------------------------

BASELINES = {
    "random": random_choice,
    "greedy_biggest": greedy_biggest,
    "cheapest": cheapest,
    "eft": eft,
    "eft_reserved": eft_reserved,
    "defects_only": defects_only,
}

WEIGHTS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4)


def late_orders(m):
    """Mean late orders per run of 120 (= % late * 1.2)."""
    return m["% late"] * 1.2


def sweep_table(seed, n_seeds, stages=False):
    """Stage 1: lock the finish-time weight w on LATENESS ONLY -- sweep w on
    the 0.1 grid (shock late orders shown alongside) and take the lowest w
    whose late orders do not exceed EFT's (w = 1.0). The 3:1 working ratio is
    irrelevant to this lock: stage 2 shows every split from 3:2 to 4:1 gives
    the same late orders at the locked w."""
    seeds = range(seed, seed + n_seeds)
    allocators = {f"{w:.1f}": make_hybrid_allocator(w) for w in WEIGHTS}
    normal = average_over_seeds(allocators, seeds, stages=stages)
    shock = average_over_seeds(allocators, seeds, shock=True, stages=stages)

    eft_late = late_orders(normal["1.0"])
    chosen = min(WEIGHTS, key=lambda w: w if late_orders(normal[f"{w:.1f}"]) <= eft_late + 1e-9
                 else float("inf"))
    if late_orders(normal[f"{chosen:.1f}"]) > eft_late + 1e-9:
        chosen = None

    variant = "--stages" if stages else "default simulator"
    print(f"STAGE 1, WEIGHT SWEEP (lock w on lateness) | NORMAL + shock column | "
          f"{variant} | seeds {seed}..{seed + n_seeds - 1}")
    print("score = w x est.finish + (1-w) x [share x defect + (1-share) x cost], "
          "each scaled 0-1; selection here uses late orders only")
    header = (f"{'w':>5}{'late orders':>13}{'late days':>11}{'% def pcs':>10}"
              f"{'cost ($)':>12}{'max share':>11}{'shock: late':>13}")
    print(header)
    print("-" * len(header))
    for w in WEIGHTS:
        n, s = normal[f"{w:.1f}"], shock[f"{w:.1f}"]
        mark = "  (= EFT)" if w == 1.0 else ("  <== locked" if w == chosen else "")
        print(f"{w:>5.1f}{late_orders(n):>13.1f}{n['late days']:>11.2f}"
              f"{n['% def pcs']:>9.1f}%{n['cost']:>12,.0f}{n['max share']:>10.0f}%"
              f"{late_orders(s):>13.1f}{mark}")
    if chosen is None:
        print(f"=> no weight matches EFT's {eft_late:.1f} late orders; keep w = 1.0")
    else:
        n = normal[f"{chosen:.1f}"]
        saving = 100 * (normal["1.0"]["cost"] - n["cost"]) / normal["1.0"]["cost"]
        print(f"=> locked w = {chosen:.1f} on lateness: lowest finish-time weight "
              f"with no more late orders than EFT ({late_orders(n):.1f} vs "
              f"{eft_late:.1f}); cost {saving:.1f}% lower")
    return chosen


def split_table(w, seed, n_seeds, stages=False):
    """Stage 2: with w locked, scan the defect:cost split. Guardrail first --
    keep only splits whose late orders still match EFT's -- then pick the
    lowest % def pcs (tiebreak cost). Selects 3:1 on the Sprint 1 data."""
    seeds = range(seed, seed + n_seeds)
    ratios = [("3:2", 0.60), ("1:1", 0.50), ("3:1", 0.75),
              ("4:1", 0.80), ("defects only", 1.00), ("cost only", 0.00)]
    allocators = {name: make_hybrid_allocator(w, defect_share=ds)
                  for name, ds in ratios}
    allocators["EFT (w=1.0)"] = make_hybrid_allocator(1.0)
    normal = average_over_seeds(allocators, seeds, stages=stages)
    shock = average_over_seeds(allocators, seeds, shock=True, stages=stages)

    eft_late = late_orders(normal["EFT (w=1.0)"])
    survivors = [(name, ds) for name, ds in ratios
                 if late_orders(normal[name]) <= eft_late + 1e-9]
    picked, picked_ds = min(survivors,
                            key=lambda r: (normal[r[0]]["% def pcs"],
                                           normal[r[0]]["cost"]))

    variant = "--stages" if stages else "default simulator"
    print(f"STAGE 2, DEFECT:COST SPLIT at locked w = {w:.1f} | {variant} | "
          f"seeds {seed}..{seed + n_seeds - 1}")
    print(f"guardrail: late orders <= EFT's {eft_late:.1f}; "
          "among the survivors pick min % def pcs (tiebreak cost)")
    header = (f"{'split':>15}{'late orders':>13}{'shock: late':>13}"
              f"{'% def pcs':>11}{'cost ($)':>12}{'  guardrail':>12}")
    print(header)
    print("-" * len(header))
    for name, _ in ratios:
        n, s = normal[name], shock[name]
        ok = late_orders(n) <= eft_late + 1e-9
        mark = "PICK" if name == picked else ("pass" if ok else "FAIL")
        print(f"{name:>15}{late_orders(n):>13.2f}{late_orders(s):>13.2f}"
              f"{n['% def pcs']:>10.2f}%{n['cost']:>12,.0f}{mark:>12}")
    n, s = normal["EFT (w=1.0)"], shock["EFT (w=1.0)"]
    print(f"{'EFT (w=1.0)':>15}{late_orders(n):>13.2f}{late_orders(s):>13.2f}"
          f"{n['% def pcs']:>10.2f}%{n['cost']:>12,.0f}")
    print(f"=> selected split {picked} (defect share {picked_ds:.2f}): "
          f"matches EFT on late orders, lowest % def pcs "
          f"{normal[picked]['% def pcs']:.2f}% among the survivors")


def baseline_table(seed, n_seeds, stages=False):
    """Fixed baselines and the chosen hybrid side by side, full metrics."""
    seeds = range(seed, seed + n_seeds)
    allocators = {**BASELINES, "hybrid_0.7": make_hybrid_allocator(0.7)}
    rows = average_over_seeds(allocators, seeds, stages=stages)
    variant = "--stages" if stages else "default simulator"
    print(f"BASELINES | NORMAL | {variant} | seeds {seed}..{seed + n_seeds - 1}")
    print_table(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--seeds", type=int, default=10, metavar="N",
                        help="average over N seeds starting at --seed (default 10)")
    parser.add_argument("--stages", action="store_true",
                        help="stage-capability variant (uses the *_stages.csv files)")
    args = parser.parse_args()

    chosen = sweep_table(args.seed, args.seeds, stages=args.stages)
    print()
    if chosen is not None:
        split_table(chosen, args.seed, args.seeds, stages=args.stages)
        print()
    baseline_table(args.seed, args.seeds, stages=args.stages)
