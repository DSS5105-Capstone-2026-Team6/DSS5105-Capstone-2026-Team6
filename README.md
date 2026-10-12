# DSS5105 Capstone 2026 — Team 6

**Track 2: The Quick-Response Subcontracting Desk** — primary objective: **minimise lateness**.

The factory (SweaterCo) farms out batches to 8 outside workshops when it is full. This system answers the dispatcher's three questions for every incoming order — *can they make it, can they take it now, are they allowed to* — makes the allocation, and leaves an auditable record with the reasoning attached.

## Project Structure

```
├── README.md                  # This file
├── data/                      # Track 2 dataset (from the course pack, see docs/CHANGELOG.md)
│   ├── orders.csv             # 120 orders
│   ├── workshops.csv          # 8 workshop profile cards
│   ├── dispatch_requests.txt  # 30 chat-style allocation requests (NL inbox)
│   ├── orders_stages.csv      # Optional --stages extension
│   ├── workshops_stages.csv   # Optional --stages extension
│   └── data_dictionary.md     # Column definitions
├── harness/
│   └── simulate.py            # Shared evaluation harness — DO NOT MODIFY
├── docs/
│   ├── Factory_Primer.md      # 3-minute domain primer
│   ├── CHANGELOG.md           # Track 2 pack changelog
│   ├── Capstone_Project_Spec_v5.pdf
│   └── Capstone_Project_Tracks_v4.pdf
├── src/                       # Our code: allocator, chat agent, tools
├── notebooks/                 # Exploration
├── tests/
├── pyproject.toml             # uv project + pinned dependencies
├── requirements.txt
└── uv.lock
```

## Quick Start

```bash
uv sync                          # or: pip install -r requirements.txt
python harness/simulate.py       # runs the three baselines (random / greedy_biggest / cheapest)
python harness/simulate.py --shock --seeds 10   # robustness scenario, averaged over 10 seeds
```

`harness/simulate.py` loads its data from `../data` — keep the `harness/` and `data/` directories as siblings.

## Evaluation Plan (Track 2)

1. **Primary objective — minimise lateness** (% late, late days; guardrail: % def pcs no worse than random). Must beat random, greedy_biggest, cheapest, and our own simple rule-based allocator.
2. **Shock scenario**: one workshop closes day 30–44; report `--shock` averaged over 10 seeds.
3. **Other objectives + hybrid**: run the same 120 orders under at least one other objective (minimise defects / fair allocation / robust) and one weighted hybrid; compare allocations. The objective is a configuration, never hard-coded.
4. **Chat inbox**: run all 30 requests in `dispatch_requests.txt`; report behaviour by kind (extract / ask / refuse / unanswerable). The LLM parses and explains — all arithmetic stays in tools.
5. **Deliverables**: tool specification table, auditable structured allocation records, dispatcher UX.

## Team Members

- Zhang Ruikai
