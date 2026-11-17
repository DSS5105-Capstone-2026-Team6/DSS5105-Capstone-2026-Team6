"""
compare_expected_work.py — weighted hybrid vs tolerance hybrid when BOTH
price a batch's work as E[work] = pieces/capacity * (1 + 0.5 * defect_rate)
(the simulator's defect model; see algorithm2.est_turnaround_expected and
simulate.py).

The Sprint-1 weighted hybrid scored est.finish as plain pieces/capacity +
transport. This benchmark re-scores it with the defect-adjusted turnaround
and puts it head-to-head with the tolerance-plateau hybrid (late_tol = 0.5)
across NORMAL/SHOCK x default/--stages, so the two hybrids are compared
under ONE time model.

    python compare_expected_work.py              # 10 seeds, 4 scenario cells
    python compare_expected_work.py --seeds 20
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from simulate import eligible_workshops, average_over_seeds, print_table
from algorithm2 import est_turnaround_expected, make_hybrid_allocator, eft
from eft_benchmark import make_weighted_allocator


def make_weighted_expected(w, defect_share=0.75):
    """Sprint-1 weighted hybrid (w=0.7, defect:cost = 3:1) but its finish
    component prices defect rework in: E[work] = work * (1 + 0.5 * defect)."""
    base = make_weighted_allocator(w, defect_share * (1 - w),
                                   (1 - defect_share) * (1 - w))
    # rebuild with the expected-work finish: make_weighted_allocator closes
    # over est_turnaround, so re-implement the scoring with the shared formula
    from eft_benchmark import _scaled

    def weighted(batch, workshops, queues):
        ok = eligible_workshops(batch, workshops)
        parts = (
            ({x.workshop_id: est_turnaround_expected(batch, x, queues)
              for x in ok}, w),
            ({x.workshop_id: x.defect_rate for x in ok}, defect_share * (1 - w)),
            ({x.workshop_id: batch["pieces"] * x.cost for x in ok},
             (1 - defect_share) * (1 - w)),
        )
        score = {}
        for component, weight in parts:
            for k, v in _scaled(component).items():
                score[k] = score.get(k, 0.0) + weight * v
        return min(score, key=lambda wid: (score[wid], wid))

    return weighted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=5105)
    ap.add_argument("--seeds", type=int, default=10)
    args = ap.parse_args()
    seeds = range(args.seed, args.seed + args.seeds)

    allocators = {
        "eft": eft,
        "weighted (plain work)": None,   # filled below (import-time formula)
        "weighted (E[work])": make_weighted_expected(0.7),
        "tolerance (tol=0.5)": make_hybrid_allocator(0.5),
    }
    from eft_benchmark import make_hybrid_allocator as sprint1_hybrid
    allocators["weighted (plain work)"] = sprint1_hybrid(0.7)

    for stages in (False, True):
        for shock in (False, True):
            rows = average_over_seeds(allocators, seeds, shock=shock,
                                      stages=stages)
            mode = "SHOCK" if shock else "NORMAL"
            variant = "--stages" if stages else "default simulator"
            print(f"EXPECTED-WORK COMPARISON | {mode} | {variant} | "
                  f"seeds {args.seed}..{args.seed + args.seeds - 1}")
            print("both weighted variants: w=0.7, defect:cost = 3:1; "
                  "tolerance: late_tol = 0.5")
            print_table(rows)


if __name__ == "__main__":
    main()
