# DSS5105 Capstone 2026 — Team 6

**Track 2: The Quick-Response Subcontracting Desk** — primary objective: **minimise lateness**.

The factory (SweaterCo) farms out batches to 8 outside workshops when it is full. This system answers the dispatcher's three questions for every incoming order — *can they make it, can they take it now, are they allowed to* — makes the allocation, and leaves an auditable record with the reasoning attached.

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
├── agent/                       # the 8 deterministic tools (no LLM) + the chat agent
│   ├── lookup_order.py          # Tool 1: order resolution (id / filters, ambiguous-safe)
│   ├── check_eligibility.py     # Tool 2: per-workshop eligible yes/no with reasons
│   ├── get_queue.py             # Tool 3: queue snapshot (as of 2026-04-01)
│   ├── estimate_delivery.py     # Tool 4: finish date, slack, cost, defect risk (one order x workshop)
│   ├── rank_candidates.py       # Tool 5: the allocator — ranked candidates, objective as config
│   ├── probe_overload.py        # Tool 6: what-if overload probe (read-only)
│   ├── earliest_feasible.py     # Tool 7: earliest date, single batch or split
│   ├── commit_allocation.py     # Tool 8: audited commit (re-checks eligibility first)
│   ├── registry.py              # tool registry + dispatch; schemas for the LLM
│   ├── llm.py                   # DeepSeek intake agent (tool-calling loop, temp 0)
│   └── inbox.py                 # batch runner: 30 requests -> JSONL of Decisions
├── desk/                        # application core: state, audit, orchestration
│   ├── contracts.py             # structured records (Decision, AllocationRecord, ...)
│   ├── state.py                 # DeskState: chat-side queues (1 Apr snapshot, commits only)
│   ├── audit.py                 # AuditLog: append-only JSONL audit trail
│   └── desk.py                  # DispatchDesk: handle() -> Decision, confirm() -> record
├── tests/                     # pytest suite: one failure case per tool (74 tests)
└── pyproject.toml             # uv project, Python 3.11
```

## Quick Start

```bash
uv sync                                     # install deps (generates uv.lock)
python harness/simulate.py                  # runs the three baselines (random / greedy_biggest / cheapest)
python harness/eft_benchmark.py --seeds 10  # EFT benchmark, normal + shock, averaged over 10 seeds
uv run pytest                               # tool unit tests (incl. failure cases)
uv run python -m agent.llm "R07: ORD-063 — 100 cardigans, make Apr 29."   # chat smoke test (needs DeepSeek key in .env)
```

`harness/simulate.py` loads its data from `../data` — keep the `harness/` and `data/` directories as siblings.

## How the System Runs

The LLM reads and explains; every number comes from a deterministic tool.

```
data/dispatch_requests.txt            (evaluation fixture: the 30 chat requests)
   │  agent/inbox.py: parse_inbox() reads the file and splits each envelope
   │  ("R07 [08:23] Ravi: <text>"); the message text passes through verbatim
   ▼
Intake agent (agent/llm.py, DeepSeek, temperature 0)
   │  parses the message, decides which tool to call; never does arithmetic
   ▼
agent/registry.py: dispatch_tool()
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
   └─ commit_allocation   → writes the audit record + updates the chat-side queue,
                            only after a human confirms
   │  structured results (numbers, reasons, candidates) go back to the agent
   ▼
The LLM composes the reply, quoting only numbers the tools returned
(tool log kept per request for the faithfulness checker)
   ▼
Dispatcher UI: candidates + estimated dates → human confirms → audit record written
```

Run one request end-to-end: `uv run python -m agent.llm R20`
Run the whole inbox and record replies + tool logs: `uv run python -m agent.inbox`

## Evaluation Plan (Track 2)

1. **Primary objective — minimise lateness** (% late, late days). Must beat random, greedy_biggest, cheapest, and our own simple rule-based allocator (EFT: 2% late, 0.2 late days on 10 seeds).
2. **Shock scenario**: one workshop closes day 30–44; report `--shock` averaged over 10 seeds.
3. **Other objectives + hybrid**: run the same 120 orders under at least one other objective (minimise defects / fair allocation / robust) and one weighted hybrid; compare allocations. The objective is a configuration, never hard-coded.
4. **Chat inbox**: run all 30 requests in `dispatch_requests.txt`; report behaviour by kind (extract / ask / refuse / unanswerable). The LLM parses and explains — all arithmetic stays in tools.
5. **Deliverables**: tool specification table, auditable structured allocation records, dispatcher UX.

## Team Members

- 
