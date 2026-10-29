# Evaluation

How the chat desk is measured: routing (behaviour), workshop choice,
faithfulness, latency — on a dev set (30 requests) and a held-out set
(20 requests, never used for tuning).

## How the system runs

The LLM reads and explains; every number comes from a deterministic tool.

```
data/dispatch_requests.txt            (evaluation fixture: the 30 chat requests)
   │  eval/run_eval.py: parse_inbox() reads the file and splits each envelope
   │  ("R07 [08:23] Ravi: <text>"); the message text passes through verbatim
   ▼
Intake agent (desk/agent.py, DeepSeek, temperature 0)
   │  parses the message, decides which tool to call; never does arithmetic
   ▼
desk/tools.py: dispatch_tool()
   ▼
Tools (pure Python, no LLM) and where each gets its facts:
   ├─ lookup_order        → data/orders.csv (id / customer / product / category)
   ├─ check_eligibility   → simulate.py's load_workshops() + eligible_workshops()
   ├─ get_queue           → workshops.csv current_queue_days (the 1 Apr chat snapshot,
   │                        kept separate from the simulator's 1 Jan state)
   ├─ estimate_delivery   → harness/algorithm2.py est_turnaround_expected()
   ├─ rank_candidates     → the allocator's ranking logic, shared with the simulator
   ├─ probe_overload      → read-only queue arithmetic
   ├─ earliest_feasible   → earliest date, single batch or split
   ├─ update_workshop_performance → learned effective capacity (roadmap §1.6)
   ├─ flag_at_risk        → committed batches × live queues, read-only
   └─ application confirm endpoint (not a model tool)
                          → validates the proposal and writes the shared ledger atomically
   │  structured results (numbers, reasons, candidates) go back to the agent
   ▼
The LLM composes the reply, quoting only numbers the tools returned
(tool log kept per request for the faithfulness checker)
   ▼
Dispatcher UI: candidates + estimated dates → human confirms → audit record written
```

Run one request end-to-end: `uv run python desk/agent.py R20`
Run the whole inbox: `python eval/run_eval.py`
Score a run: `python eval/score_run.py`
Held-out set:
`python eval/run_eval.py --inbox data/dispatch_requests_heldout.txt --out results/heldout_run.jsonl`
then `python eval/score_run.py --labels data/labels_heldout.json --results results/heldout_run.jsonl`

## Routing: how a message becomes a behaviour

The LLM never labels its own answer. `desk/router.py` reads the **tool log**
(what was called, what came back) and assigns one behaviour by a fixed
priority ladder — deterministic, reproducible, immune to wording:

| Priority | Behaviour | Trigger (tool-log evidence) |
|---|---|---|
| 1 | `refuse` | the message names a workshop `check_eligibility` ruled out (hard reasons only) |
| 2 | `allocate` | `rank_candidates` succeeded for the order the message asked about |
| 3 | `impossible` | `earliest_feasible` misses the due date even split — or (v2.2) every ranked candidate finishes late |
| 4 | `ask` | lookup returned several matches — or (v2.2) dispatch intent with an incomplete tool flow |
| 5 | `no_data` | lookup found nothing / question is outside the data (history, quotes) |
| 6 | `answer` | fallback; never a labelled ground truth |

Message text is read only for intent markers (`send/need/asap` vs
`did we/which workshop/quote`), to separate `ask` from `no_data`. Everything
safety-critical reads the tool log only.

## Faithfulness: how a reply is verified

`eval/faithfulness.py` answers roadmap risk 1 — *"the LLM states a number no
tool returned."* It never re-computes anything; it checks provenance:

1. Extract every digit-bearing token from the reply (dates in all formats,
   ids like `ORD-073`, money, percentages)
2. Build the evidence set: **every scalar in every tool result** + **numbers
   the user themselves wrote** (echoing the request is legitimate)
3. Cross-normalise date forms (`Apr 6` = `2026-04-06` = `6 Apr`), accept
   `3%` ≡ `0.03`, strip thousands separators
4. Any token with no source in the evidence set → a violation

Documented limitations: number words ("two shops") are not extracted, and
arithmetic on tool numbers ("about half of 600") is not verified — the
checker scores quoted numbers, not derived ones.

## What the evaluation measures (per request)

| Score | Question it answers | Source of truth |
|---|---|---|
| behaviour | did the system route it to the right action? | labels (Table 7 kind) |
| workshop | did the chosen workshop match ground truth? | labels |
| faithfulness | does every number trace to a tool output? | the request's tool log |
| latency | seconds per request | run records |

## Results

### Improvement journey (dev set, 30 requests)

| Version | Behaviour | Workshop | Faithfulness | Latency | What changed |
|---|---|---|---|---|---|
| v2.1 | 0.767 (23/30) | 0.842 | 0.767 | 4.5s | baseline; impossible 0/3, faithfulness hurt by self-computed price gaps |
| v2.2 | 0.900 (27/30) | 0.632 | 0.967 | 4.7s | router: all-late rank → `impossible`; unfinished dispatch flow → `ask`; prompts: no self-arithmetic |
| v2.2b | **0.933 (28/30)** | **0.842** | **0.967** | **3.6s** | tool descriptions fixed: `estimate_delivery` no longer invites per-workshop loops; comparisons go through `rank_candidates` |

Root causes were found by reading tool logs, not by tuning blind: 5 of 7
v2.1 errors fell into the `answer` fallback (model never completed the tool
flow), and the per-workshop estimate loops were induced by a tool
description that literally said "call it for every candidate".

### Held-out set (20 requests, never used for tuning) — v2.2b

| Behaviour | Workshop | Faithfulness | Latency |
|---|---|---|---|
| 0.800 (16/20) | 0.692 | **1.000** | 3.8s |

The gap vs dev is honest generalization cost; the failure review shows no
misunderstood messages, only mechanism gaps (known limitations):

- intent-marker coverage in the router ("farm it out" missed; "outside"
  = external workshop misread as dispatch intent)
- the model over-asks when message attributes already identify the order
  uniquely
- no `cost` objective in the allocator ("cheapest that hits the date")
- `impossible` decisions reached via `earliest_feasible` carry no
  best-attempt workshop for the scorer

Faithfulness generalised perfectly (1.000) — the no-self-arithmetic rule is
structural, not memorised. Held-out labels were not modified after review.

Run artefacts live in `results/`: `inbox_run*.jsonl` / `heldout_run.jsonl`
(raw decisions + tool logs) and `*_scores*.json` (per-request scores +
summary).

## Evaluation plan (Track 2)

1. **Primary objective — minimise lateness** (% late, late days). Must beat random, greedy_biggest, cheapest, and our own simple rule-based allocator (EFT: 2% late, 0.2 late days on 10 seeds).
2. **Shock scenario**: one workshop closes day 30–44; report `--shock` averaged over 10 seeds.
3. **Other objectives + hybrid**: run the same 120 orders under at least one other objective (minimise defects / fair allocation / robust) and one weighted hybrid; compare allocations. The objective is a configuration, never hard-coded.
4. **Chat inbox**: run all 30 requests in `dispatch_requests.txt`; report behaviour by kind (extract / ask / refuse / unanswerable). The LLM parses and explains — all arithmetic stays in tools.
5. **Deliverables**: tool specification table, auditable structured allocation records, dispatcher UX.
