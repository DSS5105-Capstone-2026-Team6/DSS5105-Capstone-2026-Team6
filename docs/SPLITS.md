# Splitting an order across workshops

The track brief: *"Splits live in your chat layer and its record; the
simulator sends one batch to one workshop."* So splits are a chat-desk
option only. `harness/simulate.py` and every simulator result stay
single-batch.

Code: `split_options()` and `_best_split_for()` in `desk/tools.py`;
the desk attaches them in `DispatchDesk._attach_split()` and commits one
with `DispatchDesk.confirm_split()`.

## When the desk offers splits

- Always for an **IMPOSSIBLE** order (no single workshop meets the due date).
- For an **ALLOCATE** only when the flow called `earliest_feasible`, e.g.
  the message asked about splitting.
- Only splits that finish **earlier than the best single workshop** are shown.
- A split that meets the due date while no single shop does is *not*
  re-labelled ALLOCATE; the routing labels stay as they are (intentional).

## The algorithm

Every workshop in a split works in parallel, so the order finishes when its
slowest part finishes. Each part uses the same time model as every other
tool (from `harness/algorithm2.py`):

    finish(n pieces at shop w) = queue_w + n / capacity_w × (1 + 0.5 × defect_rate_w) + lead_days_w

**Step 1: the best split for one set of workshops** (`_best_split_for`).
For a finish time T, shop w can complete

    can_make_w(T) = floor((T − queue_w − lead_days_w) × capacity_w / (1 + 0.5 × defect_rate_w))

pieces, capped at its `max_batch_pieces` (e.g. FreshStart's 300).
`can_make` only grows with T, so a binary search (60 halvings) finds the
earliest T at which the shops together cover the order, with every shop
getting at least the minimum part. That T is the earliest possible finish
for this set. Each shop then takes `can_make_w(T)`, and the surplus pieces
are handed back from the part that finishes last. Finally every part is
re-checked with the normal eligibility rule.

**Step 2: every set of workshops** (`split_options`).
Try every set of 2 or more eligible workshops. There is no ceiling on the
number of workshops, and at most 7 shops are eligible, so this is at most
120 sets and takes milliseconds.

**Step 3: drop splits that don't make sense.**
- Each part must carry at least 10% of the order (`min_part_share`), so no
  token 1-piece parts.
- A split is dropped when a split over a subset of its workshops finishes
  at least as early: an extra workshop must make the order earlier to be
  worth its extra pickup and quality check.

**Step 4: rank exactly like the candidates.** Split options go through the
same ranking function as single workshops (`order_rows` in
`desk/allocator.py`, used by `rank_candidates`), with the proposal's
objective:
- **lateness** (default): expected days late, then expected finish, then
  defect rate, then cost.
- **defects**: defect rate (piece-weighted over the parts), then expected
  days late, then finish, then cost.
- **hybrid**: keep the plateau within `late_tol` (0.5 days) of the least
  expected lateness, then the lowest defect rate.

Expected days late = max(0, expected finish − days until the due date), the
same continuous measure the candidates use. The top 5 are shown, each with
its own **Confirm split #k** button.

**Recommendation.** On an IMPOSSIBLE order the ⭐ recommendation moves from
the best single workshop to split #1 (`Decision.recommended_split = 0`),
since every listed split finishes earlier than any single shop. `chosen`
stays the best single workshop as the fallback, so the evaluation's
workshop check is unchanged. On an ALLOCATE the single workshop keeps the ⭐.

## Example: ORD-029 (1500 beanies, due Apr 1)

| # | Split | Finish | Days late |
|---|-------|--------|-----------|
| 1 | 449 SteadyHands + 394 Little Loom + 657 Nimble Needle | Apr 8 | 7 |
| 2 | 673 SteadyHands + 827 Nimble Needle | Apr 10 | 9 |
| 3 | 552 Little Loom + 948 Nimble Needle | Apr 10 | 9 |
| 4 | 914 SteadyHands + 586 Little Loom | Apr 11 | 10 |

The best single workshop (SteadyHands) finishes Apr 14, 13 days late.

## Committing a split

`confirm_split(decision, k)` commits all parts of option k in one
transaction, or none of them. Each part becomes its own audit record
(`evidence.split = {"part": i, "of": n, "parts": [...]}`) and moves only its
own workshop's queue. It re-checks eligibility, exclusions and that the
parts add up to the order, refreshes a stale proposal instead of committing
it, and refuses an order that was already committed (single or split).

## Limits

- Within one set of workshops the piece split minimises the finish date;
  the objective then decides between the sets.
- `earliest_feasible` (the tool the model calls, and which the router reads)
  still reports the best two-workshop split; tests check that its date
  matches the best two-shop option here.
- The Telegram bot confirms single workshops only.
