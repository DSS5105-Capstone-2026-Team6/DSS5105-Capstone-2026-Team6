# The Allocator (algorithm2)

One time model everywhere — simulator replay, desk tools and the SQLite
ledger all share it, so online and offline can never diverge:

```
E[finish] = queue_days + pieces / capacity × (1 + 0.5 × defect_rate) + pickup_lead_days
```

(`pickup_lead_days` is the transport time.)

The `1 + 0.5 × defect_rate` term prices defect rework as an expectation: in
the simulator a defective batch (probability `defect_rate`) is redone at
1.5× work.

## Constraints

A workshop is eligible only if ALL hold:

- it makes the order's category (`makes` vs TOPS / ACCESSORIES)
- it is not `SUSPENDED`
- the batch fits its `max_batch_pieces` cap
- it is not excluded by a named person in the request
- (stages mode) it covers the order's remaining stages

## Selection policy — lateness first, defects second (the hybrid)

1. First constraint: `expected_days_late = max(0, E[finish] − slack)` —
   finishing early counts as 0 days late
2. Keep the **plateau**: workshops within `late_tol` days of the best
   achievable lateness; when nobody is late (best = 0), tighten the plateau
   to within `late_tol` of the earliest finish so queues stay short
3. Inside the plateau pick the **lowest defect rate** (tiebreak: E[finish],
   cost, workshop id)

## How `late_tol` was found

A two-stage scan over 10 tolerances (0–10 days) × 10 seeds (5105–5114)
× {normal, shock} × {default, stages}, run by `harness/algorithm2.py`:
stage 1 keeps only tolerances achieving the minimum (% late, late days);
stage 2 picks the lowest defect percentage among the keepers (tiebreak
cost, smaller tol). The picks land at 0.0–0.5 depending on scenario;
**production runs 0.5** — within 0.1pt of the best % late in every
scenario and the pick for stages-normal.

## Performance (10 seeds, default simulator)

| Policy | % late | late days | cost ($) | max share |
|---|---|---|---|---|
| random | 34% | 6.1 | 111,780 | 23% |
| greedy_biggest | 84% | 26.5 | 108,430 | 70% |
| cheapest | 92% | 81.9 | 85,960 | 70% |
| EFT (earliest finish) | 2% | 0.2 | 115,592 | 26% |
| **hybrid (tol=0.5)** | **2%** | **0.2** | 115,639 | 27% |

Under shock (a workshop closed day 30–44) the hybrid holds at 2% late /
0.2 late days — matching EFT on lateness while carrying a lower defect
load by construction.

Reproduce: `python harness/algorithm2.py` (tables + tolerance scan),
`python harness/eft_benchmark.py --seeds 10` (EFT benchmark + the
accessory-reservation experiment).

## Appendix

| Full scan across the four scenario cells (seeds 5105–5114, mean over 10 seeds)| [Tolerance_Scan.md](Tolerance_Scan.md) |

### Why these values were chosen

- **Lateness is flat for small tolerances (0–0.5) and degrades quickly beyond ~5 days** — at tol = 10, % late rises to 8–14%. Since the selection hierarchy is *lateness first*, any tolerance that sacrifices lateness is eliminated at stage 1 of the scan.
- **Larger tolerances trade lateness for fewer defects and lower cost** (% def pcs 7.5% → 5.0–5.4%, up to ~$6.7k cheaper), which violates the lateness-first hierarchy and is rejected despite looking attractive on the secondary metrics.
- **Three of the four cells select `late_tol = 0`**; only NORMAL·--stages selects **0.5** (its stage-1 plateau favors 0.5's better late days, 0.23 vs 0.27). Production runs **0.5** — within 0.1pt of the best % late in every scenario and matching the pick for stages-normal, giving a single robust default across all cells.

