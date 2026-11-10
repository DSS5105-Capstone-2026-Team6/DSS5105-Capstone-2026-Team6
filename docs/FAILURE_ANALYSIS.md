# Failure Analysis — 12 cases, re-evaluated on the Sprint 3 code

Scope: every request that failed at least one metric in the last live runs
(dev 30 requests, `results/inbox_run_v22b.jsonl`, 28 Oct; held-out 20
requests, `results/heldout_run.jsonl`, 29 Oct), re-checked against the code
on `main` @ `18ccf99` (10 Nov) plus the refusal-alternative fix on `spr3`
(case 7). Labels: `data/labels_inbox.json`,
`data/labels_heldout.json`; held-out labels were not edited after review.

## 1. How the re-evaluation was done

The scored runs predate Sprint 3, and many desk changes landed after them
(PR #20 on 30 Oct and later commits). A fresh live run needs a DeepSeek key, so
we ran an **offline replay** instead (`python eval/replay_offline.py`):

- each record's **recorded LLM reply and tool log** are fed back through the
  **current** `DispatchDesk.handle_message`: the router, ranking attach,
  recommendation consistency, `_fill_impossible`, the refusal alternative
  and split attach;
- the output is scored with the unchanged `eval/score_run.py`.

The LLM step is held fixed, so the difference from the original scores comes only
from code changes. Changes that act *through* the model (prompt edits, new
tool messages the model would read) are **not** captured; §4 lists them.
Re-scoring the original runs with the current scorer reproduces the
committed numbers exactly.

| Set | Run | Behaviour | Workshop | Faithfulness |
|---|---|---|---|---|
| Dev (30) | v2.2b, 28 Oct (as reported) | 0.933 (28/30) | 0.842 (16/19) | 0.967 (29/30) |
| Dev (30) | Sprint 3 code, offline replay | 0.933 (28/30) | **0.895 (17/19)** | 0.967 (29/30) |
| Held-out (20) | v2.2b, 29 Oct (as reported) | 0.800 (16/20) | 0.692 (9/13) | 1.000 (20/20) |
| Held-out (20) | Sprint 3 code, offline replay | 0.800 (16/20) | **0.846 (11/13)** | 1.000 (20/20) |

On dev, two cases were fixed (R21, R24) and one new failure appeared (R17),
see below. The dev set was used for tuning; the held-out set was never tuned
on.

Behaviour accuracy by request kind (held-out, unchanged by the replay):
ambiguous 2/2, constraint 4/4, impossible 2/2, ineligible 3/3,
unanswerable 2/3, **complete 2/4, missing 1/2**.

## 2. The 12 cases at a glance

| # | ID | Set | Kind | Expected | Got (Sprint 3 code) | Fails | Root cause | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | R05 | dev | missing | ask | answer | behaviour | intent markers miss "line something up" | open |
| 2 | H04 | held-out | missing | ask | answer | behaviour | intent markers miss "farm it out" | open |
| 3 | H08 | held-out | unanswerable | no_data | ask | behaviour | "outside" read as dispatch intent; "which *outside* workshop" misses the query marker | open |
| 4 | R28 | dev | impossible | impossible, W1 | ask | behaviour + workshop | model stopped to question an overdue date instead of checking feasibility | open |
| 5 | H07 | held-out | complete | allocate W6 | ask | behaviour + workshop | model looked up by customer only; asked although one open order fits | open; tool fix exists, needs live re-run |
| 6 | H20 | held-out | complete | allocate W6/W2 | ask | behaviour + workshop | same as H07: the pieces filter was not used | open; tool fix exists, needs live re-run |
| 7 | R24 | dev | ineligible | refuse + W6 | refuse + W6 | — | refusal correct, but model offered to rank instead of ranking | **fixed** (refusal alternative, `spr3`) |
| 8 | R15 | dev | ambiguous | ask | ask | faithfulness | model counted "6 open orders" itself (number not in tool output) | open; tool now states the count, needs live re-run |
| 9 | R17 | dev | complete | allocate W1 | allocate **W6** | workshop | model overrode the allocator in prose; button now follows prose | **new in Sprint 3** |
| 10 | R21 | dev | constraint | allocate W5 | allocate W5 | — | "cheapest on time" handled in prose, button followed the ranking | **fixed** (PR #20) |
| 11 | H09 | held-out | constraint | allocate W3 | allocate W3 | — | same as R21 | **fixed** (PR #20) |
| 12 | H14 | held-out | impossible | impossible, W2 | impossible, W2 | — | IMPOSSIBLE via `earliest_feasible` carried no best-attempt shop | **fixed** (`_fill_impossible`, PR #20) |

Eight cases still fail on the current code; four were fixed (three by PR #20,
R24 by the refusal-alternative change), and one of the PR #20 changes caused a
new failure (R17).

## 3. Case-by-case analysis

### Case 1 — R05 (dev, missing info)

- **Input:** "ORD-066 due date just moved up — will confirm the new date after the call, but line something up."
- **Expected:** `ask` for the new due date (optionally pre-check candidates).
- **Got:** `answer`. The model made **no tool calls** and wrote a correct
  question ("I need the new due date…").
- **Why:** behaviour is assigned by code from the tool log, never from the
  prose. With an empty log, the router's last chance to turn this into `ask`
  is the dispatch-intent check (`_ALLOC_MARKERS` in `desk/router.py`), and
  "line something up" contains none of those markers, so the message falls
  through to `answer`.
- **Impact:** low for the user, because the text does ask. But the structured
  output says `answer`, so the UI shows no pending request.
- **Fix next:** widen intent markers ("line … up", "farm", "free", "room"),
  or treat any message that names an order id with no completed tool flow as
  `ask`.

### Case 2 — H04 (held-out, missing info)

- **Input:** "Factory says ORD-114 is stuck. Farm it out — Northwind will give us the new date after their call. See who's free."
- **Expected:** `ask` for the revised due date.
- **Got:** `answer`. The model looked up ORD-114 and asked for the new date.
- **Why:** same mechanism as R05. "Farm it out" and "see who's free" are not
  in `_ALLOC_MARKERS`. This was listed as a known gap in
  `docs/EVALUATION.md` and is still open.
- **Fix next:** same as R05. Keyword lists will keep missing new phrasings;
  a small intent classifier on the message, or the LLM's own structured
  intent field validated by code, would generalise better.

### Case 3 — H08 (held-out, unanswerable)

- **Input:** "Quick one — which outside workshop have we used the most since January? Boss wants it before the review."
- **Expected:** `no_data`, because the dataset has no allocation history.
- **Got:** `ask`. The model correctly said no tool reports usage history.
- **Why:** two keyword collisions in the router. "which outside workshop"
  does not match the query marker `"which workshop"`, and "outside" **is** a
  dispatch marker, so `_looks_like_data_question` is false and
  `_looks_like_alloc_request` is true, which gives `ask`.
- **Fix next:** match query intent on patterns ("which … workshop", "most",
  "since <month>") and stop using "outside" as a dispatch signal on its own.

### Case 4 — R28 (dev, impossible)

- **Input:** "Sending ORD-002 outside — 1000 crewneck sweaters. Who has room this week? Due Mar 29."
- **Expected:** `impossible`, best attempt W1 (QuickStitch, 9 Apr).
- **Got:** `ask`. The model called `lookup_order` and `get_queue`, then asked
  whether the 29 Mar due date was still right, because it is before the
  1 Apr snapshot.
- **Why:** the model never called `earliest_feasible` or `rank_candidates`.
  With no feasibility evidence in the log, the router can only fall back to
  `ask`. The question is reasonable, but the desk should *show* that the
  order cannot be made by any shop and then ask.
- **Fix next:** in code, when the looked-up due date is before the world date,
  run `earliest_feasible` automatically (like `_fill_impossible`) so the
  outcome no longer depends on the model choosing to check.

### Case 5 — H07 (held-out, complete)

- **Input:** "The Loom & Leaf beanie job — the small one — can someone dispatch it today?"
- **Expected:** `allocate` ORD-035 → W6.
- **Got:** `ask` ("can you confirm ORD-035?"). The model called
  `lookup_order(customer="Loom & Leaf")` only, received 6 open orders
  (`ambiguous`), and the router correctly mapped `ambiguous` to `ask`.
- **Why:** the message identifies one order (beanie + Loom & Leaf, and only
  one is open), but the product was not passed to the tool.
- **Sprint 3 status:** PR #20 (`8d12442`) made `lookup_order` hide completed
  orders and accept `product`/`pieces`/`due_date` filters, and told the
  prompt to pass every detail. Checked directly on the current code:
  `lookup_order(customer="Loom & Leaf", product="beanie")` → `found`
  ORD-035. Whether the model now passes `product` can only be confirmed by a
  live run, so the case stays **open**.

### Case 6 — H20 (held-out, complete)

- **Input:** "TrendCart's beanie reorder — 1000 pieces, ship by Apr 17 — get it outside today."
- **Expected:** `allocate` ORD-096 → W6 or W2.
- **Got:** `ask`. The lookup with customer and product returned 3 matches.
- **Why:** the 1000-piece quantity was not used as a filter.
- **Sprint 3 status:** current `lookup_order(customer="TrendCart",
  product="beanie")` still returns 2 open orders (ORD-096, ORD-082). With
  `pieces=1000` it returns `found` ORD-096. The fix depends on the model
  passing `pieces`, so the case stays **open** until a live run.

### Case 7 — R24 (dev, ineligible)

- **Input:** "Little Loom does lovely work — ORD-015 to them?"
- **Expected:** `refuse` (Little Loom makes accessories only; ORD-015 is
  vests) **and** offer the best eligible alternative, W6.
- **Got:** `refuse` with a correct reason, but no alternative. The model
  listed the six eligible shops and asked "Want me to rank them?"
- **Why:** the model stopped after `check_eligibility`. With no
  `rank_candidates` call there is no alternative to attach.
- **Fixed:** after a REFUSE with no candidates, the desk now ranks the
  eligible workshops in code (`_fill_refusal_alternative` in `desk/desk.py`,
  the same pattern as `_fill_impossible`) and appends the best alternative to
  the reply ("Reply yes to commit ORD-015 to W6"). The offline replay now
  picks W6 ✅. Tests: `tests/test_skip_and_duplicates.py`.

### Case 8 — R15 (dev, ambiguous; faithfulness)

- **Input:** "Boss wants the Loom & Leaf stuff outside asap."
- **Expected:** `ask` which order. Behaviour was **correct**.
- **Failed:** faithfulness. The reply says "13 orders on file, and **6** of
  them are still open". The faithfulness checker could not trace "6" to any
  tool output: the model counted the list itself, which breaks the
  "LLM never does arithmetic" rule.
- **Sprint 3 status:** `lookup_order` now returns the count in its message
  ("6 open orders match (7 completed order(s) not shown)"), so a live run
  should pass. Not verified without a live run.

### Case 9 — R17 (dev, complete) — new failure from a Sprint 3 change

- **Input:** "ORD-017 — 800 cardigans for TrendCart. Factory is full, this one goes outside. Back by Apr 10 please."
- **Expected:** `allocate` W1 (QuickStitch, 9 Apr; lateness objective).
- **Got (Sprint 3 code):** `allocate` **W6**.
- **What happened:** the allocator chose W1, but the model wrote "W6 looks
  like the better call… Reply yes to commit ORD-017 to W6". In the
  original run the structured choice stayed W1, so the score was a pass, but
  **the confirm button (W1) and the text (W6) disagreed**. PR #20 made the
  button follow the text's recommendation (and logs a warning), so the
  replay now commits W6.
- **Why it matters:** the earlier pass hid a real inconsistency. The fix made
  the system honest, but it also lets the model's own judgement override the
  allocator. Under the current default objective (hybrid), the allocator
  itself also picks W6. The label was written for the lateness objective, so
  this case is partly a **label/objective mismatch** (see §4).
- **Fix next:** follow the prose only when the user stated a constraint
  ("cheapest", "not W1"). Otherwise keep the allocator's pick and have the
  model mention the alternative instead of recommending it.

### Case 10 — R21 (dev, constraint) — fixed

- **Input:** "ORD-081 — 1500 crewneck sweaters for Harbor Knits, due Apr 13. Margin is thin on this one — cheapest shop that can still make Apr 13."
- **Expected:** W5 (GiantWeave, cheapest on-time).
- **Original run:** the model correctly recommended W5 in text, but the
  ranking (lateness) chose W1, and the button committed W1.
- **Now:** PR #20 recommendation consistency makes the button follow the
  reply → W5 ✅.
- **Remaining gap:** the allocator has no `cost` objective, so "cheapest that
  still meets the date" is solved in prose, not in a tool. A
  cost-within-deadline objective in `rank_candidates` would make this
  deterministic.

### Case 11 — H09 (held-out, constraint) — fixed

- **Input:** "ORD-010. 1000 cardigans, Cotton Club, due Apr 25. Margin's gone on this one — cheapest shop that still hits the date."
- **Expected:** W3 (BudgetWorks, $800, 14 Apr).
- **Original run:** text recommended W3, button committed W1.
- **Now:** fixed by the same change as R21 → W3 ✅. Same remaining gap
  (no cost objective).

### Case 12 — H14 (held-out, impossible) — fixed

- **Input:** "ORD-029 is due TODAY. 1500 beanies for Northwind. Someone tell me we can still make it."
- **Expected:** `impossible`, best attempt W2 (SteadyHands, 14 Apr).
- **Original run:** behaviour `impossible` was correct (via
  `earliest_feasible`), but no candidate was attached, so the workshop
  score failed.
- **Now:** `_fill_impossible` (PR #20) ranks the order in code when an
  IMPOSSIBLE has no candidates → W2 ✅.

## 4. Patterns, limitations, and what we would fix next

**Failure patterns (8 open cases):**

| Pattern | Cases | Next fix |
|---|---|---|
| Keyword intent rules miss phrasings | R05, H04, H08 | pattern-based / classifier intent, drop "outside" as a lone signal |
| Model stops before the deciding tool call | R28 (R24 fixed) | run feasibility in code when the due date is already past, as the refusal fix now does for ranking |
| Model under-uses lookup filters | H07, H20 | tool fix shipped; confirm with a live run |
| Model does its own counting | R15 | tool now returns the count; confirm with a live run |
| Model prose overrides the allocator | R17 | follow prose only when the user stated a constraint |

**Limitations of this evaluation:**

1. **Offline replay, not a live run.** The model's replies are from 28–29 Oct.
   Prompt and tool-message changes (H07, H20, R15) are untested. A live
   `eval/run_eval.py` on both sets is the next step.
2. **Labels assume the lateness objective; the default is now hybrid.**
   Checked directly with `rank_candidates` on the current code: for 2 of the
   11 unconstrained (`complete`) dev+held-out allocation requests the default
   (hybrid) pick differs from the label (R07: W8 vs W6; R17: W6 vs W1). A
   live run would therefore score these against labels written for another
   objective. Either re-label for hybrid or evaluate with `objective=lateness`.
3. **Small samples.** 20 held-out requests: one case moves accuracy by 5
   points, and per-kind results rest on 2–4 requests each.
4. **The scorer checks the structured decision**, not whether the text and the
   button agree. R17 passed in the original run despite such a disagreement.
   A consistency metric would catch this.

## 5. Reproduce

```bash
uv run python eval/replay_offline.py
```

Prints both sets' scores and failing ids. To keep the replay files, run
with `--out-dir results`.
