# DSS5105 Capstone 2026 — Team 6

**Track 2: The Quick-Response Subcontracting Desk** — primary objective: **minimise lateness**.

The factory (SweaterCo) farms out batches to 8 outside workshops when it is full. This system answers the dispatcher's three questions for every incoming order — *can they make it, can they take it now, are they allowed to* — makes the allocation, and leaves an auditable record with the reasoning attached.

## The Allocator (algorithm2)

One time model everywhere — simulator replay, desk tools and the SQLite
ledger all share it, so online and offline can never diverge:

```
E[finish] = queue_days + pieces / capacity × (1 + 0.5 × defect_rate) + pickup_lead_days
```

The `1 + 0.5 × defect_rate` term prices defect rework as an expectation: in
the simulator a defective batch (probability `defect_rate`) is redone at
1.5× work.

**Constraints (a workshop is eligible only if ALL hold):**

- it makes the order's category (`makes` vs TOPS / ACCESSORIES)
- it is not `SUSPENDED`
- the batch fits its `max_batch_pieces` cap
- it is not excluded by a named person in the request
- (stages mode) it covers the order's remaining stages

**Selection policy — lateness first, defects second (the hybrid):**

1. First constraint: `expected_days_late = max(0, E[finish] − slack)` —
   finishing early counts as 0 days late
2. Keep the **plateau**: workshops within `late_tol` days of the best
   achievable lateness; when nobody is late (best = 0), tighten the plateau
   to within `late_tol` of the earliest finish so queues stay short
3. Inside the plateau pick the **lowest defect rate** (tiebreak: E[finish],
   cost, workshop id)

**How `late_tol` was found** — a two-stage scan over 10 tolerances
(0–10 days) × 10 seeds (5105–5114) × {normal, shock} × {default, stages},
run by `harness/algorithm2.py`: stage 1 keeps only tolerances achieving the
minimum (% late, late days); stage 2 picks the lowest defect percentage
among the keepers (tiebreak cost, smaller tol). The picks land at 0.0–0.5
depending on scenario; **production runs 0.5** — within 0.1pt of the best
% late in every scenario and the pick for stages-normal.

**Performance (10 seeds, default simulator):**

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

## Deployed Apps
Streamlit App: https://dss5105-capstone-2026-team6-yrcuaguw78h57dg9dc4pmi.streamlit.app

Dispatcher Bot (Deployed on PC): https://t.me/Ddispatcherr_bot
## Project Structure

```
├── README.md                  # This file
├── data/                      # Track 2 dataset (shared simulator input)
│   ├── orders.csv             # 120 orders
│   ├── workshops.csv          # 8 workshop profile cards
│   ├── dispatch_requests.txt  # 30 chat-style allocation requests (NL inbox)
│   ├── orders_stages.csv      # Optional --stages extension
│   ├── workshops_stages.csv   # Optional --stages extension
│   └── data_dictionary.md     # Column definitions
├── harness/
│   ├── simulate.py            # Shared evaluation harness — DO NOT MODIFY
│   ├── eft_benchmark.py       # EFT benchmark + accessory-reservation experiment
│   └── algorithm2.py          # Lateness-first hybrid allocator + tolerance scan
├── desk/                        # application core: state, audit, orchestration
│   ├── contracts.py             # structured records (Decision, AllocationRecord, ...)
│   ├── config.py                # central constants: model, API and data/results paths
│   ├── register.py              # OrderStore + WorkshopStore (shared data stores)
│   ├── tools.py                 # the 8 deterministic tools (no LLM) + tool registry
│   ├── allocator.py             # Tool 5: the allocator — ranked candidates, objective as config
│   ├── agent.py                 # DeepSeek intake agent (tool-calling loop, temp 0)
│   ├── router.py                # code-assigned behaviour: tool log -> Decision
│   ├── prompts/dispatcher.txt   # system prompt, dispatcher persona (Streamlit desk)
│   ├── prompts/group.txt        # system prompt, group-chat persona (Telegram bot)
│   ├── state.py                 # DeskState: chat-side queues (1 Apr snapshot, commits only)
│   ├── audit.py                 # AuditLog: append-only JSONL audit trail
│   └── desk.py                  # DispatchDesk: handle_message() -> Decision, confirm() -> record
├── adapter/                   # Telegram bot shell around DispatchDesk (bot branch)
│   ├── session.py             # per-chat session: trigger filter + confirmation gate (pure, tested)
│   └── telegram_bot.py        # python-telegram-bot wiring; zero business logic
├── app/
│   ├── streamlit_app.py       # Dispatcher UI: candidates + estimated dates → human confirms → audit record written
├── eval/
│   ├── run_eval.py              # batch runner: 30 requests -> JSONL of Decisions (+ latency)
│   ├── score_run.py             # scores a run vs labels: behaviour / workshop / faithfulness
│   └── faithfulness.py          # every number in the reply must trace to the tool log
├── tests/                     # pytest suite: one failure case per feature (181 tests)
└── pyproject.toml             # uv project, Python 3.11
```

## Safety and deployment

See [deployment and migration notes](docs/DEPLOYMENT.md) before upgrading.
The model tools are read-only. Human confirmation uses a transactionally shared
SQLite allocation ledger; follow-ups update the pending proposal. Public
Streamlit deployments require `APP_PASSWORD`, and every provider requires its
own key (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Server-side
API call budgets survive new sessions and Reset demo.

SQLite shares state within one host; a separately hosted Telegram bot needs an
external database to share state with Streamlit. Local cloud disk is not durable
across all redeployments. Existing JSONL audit records are imported once.

## Quick Start

```bash
uv sync                                     # install deps (generates uv.lock)
python harness/simulate.py                  # runs the three baselines (random / greedy_biggest / cheapest)
python harness/eft_benchmark.py --seeds 10  # EFT benchmark, normal + shock, averaged over 10 seeds
uv run pytest                               # tool unit tests (incl. failure cases)
uv run python desk/agent.py "R07: ORD-063 — 100 cardigans, make Apr 29."   # chat smoke test (needs DeepSeek key in .env)
```

`harness/simulate.py` loads its data from `../data` — keep the `harness/` and `data/` directories as siblings.

## How the System Runs

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
Run the whole inbox and record replies + tool logs: `python eval/run_eval.py`
Score the run against the labelled inbox (Table 7 ground truth):
`python eval/score_run.py` — reports behaviour accuracy by kind, workshop
accuracy, and faithfulness (numbers traced to the tool log). The held-out
set (`data/dispatch_requests_heldout.txt` + `data/labels_heldout.json`)
runs and scores the same way:
`python eval/run_eval.py --inbox data/dispatch_requests_heldout.txt --out results/heldout_run.jsonl`

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

### What the evaluation measures (per request)

| Score | Question it answers | Source of truth |
|---|---|---|
| behaviour | did the system route it to the right action? | labels (Table 7 kind) |
| workshop | did the chosen workshop match ground truth? | labels |
| faithfulness | does every number trace to a tool output? | the request's tool log |
| latency | seconds per request | run records |

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

Run artefacts live in `results/`: `inbox_run*.jsonl` (raw decisions + tool
logs) and `inbox_scores*.json` (per-request scores + summary).

## Evaluation Plan (Track 2)

1. **Primary objective — minimise lateness** (% late, late days). Must beat random, greedy_biggest, cheapest, and our own simple rule-based allocator (EFT: 2% late, 0.2 late days on 10 seeds).
2. **Shock scenario**: one workshop closes day 30–44; report `--shock` averaged over 10 seeds.
3. **Other objectives + hybrid**: run the same 120 orders under at least one other objective (minimise defects / fair allocation / robust) and one weighted hybrid; compare allocations. The objective is a configuration, never hard-coded.
4. **Chat inbox**: run all 30 requests in `dispatch_requests.txt`; report behaviour by kind (extract / ask / refuse / unanswerable). The LLM parses and explains — all arithmetic stays in tools.
5. **Deliverables**: tool specification table, auditable structured allocation records, dispatcher UX.

## Team Members

-
