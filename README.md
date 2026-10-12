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
│   └── eft_benchmark.py       # EFT benchmark + accessory-reservation experiment
├── tests/                     # pytest suite (Sprint 2)
└── pyproject.toml             # uv project, Python 3.11
```

## Quick Start

```bash
uv sync                                     # install deps (generates uv.lock)
python harness/simulate.py                  # runs the three baselines (random / greedy_biggest / cheapest)
python harness/eft_benchmark.py --seeds 10  # EFT benchmark, normal + shock, averaged over 10 seeds
```

`harness/simulate.py` loads its data from `../data` — keep the `harness/` and `data/` directories as siblings.

## Evaluation Plan (Track 2)

1. **Primary objective — minimise lateness** (% late, late days). Must beat random, greedy_biggest, cheapest, and our own simple rule-based allocator (EFT: 2% late, 0.2 late days on 10 seeds).
2. **Shock scenario**: one workshop closes day 30–44; report `--shock` averaged over 10 seeds.
3. **Other objectives + hybrid**: run the same 120 orders under at least one other objective (minimise defects / fair allocation / robust) and one weighted hybrid; compare allocations. The objective is a configuration, never hard-coded.
4. **Chat inbox**: run all 30 requests in `dispatch_requests.txt`; report behaviour by kind (extract / ask / refuse / unanswerable). The LLM parses and explains — all arithmetic stays in tools.
5. **Deliverables**: tool specification table, auditable structured allocation records, dispatcher UX.

## Team Members

- 
