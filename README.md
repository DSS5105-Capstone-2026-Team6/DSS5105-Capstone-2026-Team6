# DSS5105 Capstone 2026 — Team 6

**Track 2: The Quick-Response Subcontracting Desk** — primary objective: **minimise lateness**.

The factory (SweaterCo) farms out batches to 8 outside workshops when it is full. This system answers the dispatcher's three questions for every incoming order — *can they make it, can they take it now, are they allowed to* — makes the allocation, and leaves an auditable record with the reasoning attached.

## Deployed Apps

Streamlit App: https://dss5105-capstone-2026-team6-yrcuaguw78h57dg9dc4pmi.streamlit.app

Dispatcher Bot (Render): https://t.me/Ddispatcherr_bot

## Headline results

| Metric | Value | Where verified |
|---|---|---|
| Lateness (10 seeds, normal / shock) | **2% late, 0.2 late days** | [docs/ALLOCATOR.md](docs/ALLOCATOR.md) |
| Chat behaviour accuracy (dev 30 / held-out 20) | **0.933 / 0.800** | [docs/EVALUATION.md](docs/EVALUATION.md) |
| Faithfulness (numbers traced to tool outputs) | **0.967 dev / 1.000 held-out** | [docs/EVALUATION.md](docs/EVALUATION.md) |
| Tool calls | 10 deterministic tools, LLM never does arithmetic | [docs/EVALUATION.md](docs/EVALUATION.md) |

The allocator is a **lateness-first hybrid**: expected finish with defect
rework priced in, a tolerance plateau among on-time workshops, lowest defect
rate inside the plateau. Detail: [docs/ALLOCATOR.md](docs/ALLOCATOR.md) & [docs/Tolerance_Scan.md](docs/Tolerance_Scan.md)

The desk itself: 10 deterministic tools · LLM intake (DeepSeek/GPT/Claude)
· code-assigned behaviour routing · a transactional allocation ledger (local
SQLite per session, or a shared Supabase PostgreSQL for web + bot) · learned
workshop performance · a Streamlit dispatcher UI (live queues, allocator
lens, world switch Apr-1/Jan-1, stages mode, shock trigger, LLM parser,
batch confirm) and a Telegram bot shell (one-tap commit buttons, /queue
charts, yes all).

Further reading: [deployment & migration notes](docs/DEPLOYMENT.md) ·
[shared database setup & acceptance](docs/SHARED_DATABASE.md).

## Project Structure

```
├── README.md                  # This file
├── docs/                      # ALLOCATOR (algorithm) · EVALUATION (routing, faithfulness) · FAILURE_ANALYSIS · DEPLOYMENT
├── data/                      # Track 2 dataset (shared simulator input)
│   ├── orders.csv             # 120 orders
│   ├── workshops.csv          # 8 workshop profile cards
│   ├── dispatch_requests.txt  # 30 chat-style allocation requests (NL inbox)
│   ├── dispatch_requests_heldout.txt  # 20 held-out requests (never tuned on)
│   ├── orders_stages.csv      # Optional --stages extension
│   ├── workshops_stages.csv   # Optional --stages extension
│   └── data_dictionary.md     # Column definitions
├── harness/
│   ├── simulate.py            # Shared evaluation harness — DO NOT MODIFY
│   ├── eft_benchmark.py       # EFT benchmark + accessory-reservation experiment
│   └── algorithm2.py          # Lateness-first hybrid allocator + tolerance scan
├── desk/                        # application core: state, audit, orchestration
│   ├── contracts.py             # structured records (Decision, AllocationRecord, ...)
│   ├── config.py                # central constants + the switchable world clock (Apr-1 / Jan-1)
│   ├── register.py              # OrderStore + WorkshopStore (shared data stores)
│   ├── tools.py                 # the 10 deterministic tools (no LLM) + tool registry
│   ├── performance.py           # learned workshop performance (roadmap §1.6, SQLite-backed)
│   ├── allocator.py             # Tool 5: the allocator — ranked candidates, objective as config
│   ├── agent.py                 # intake agent (tool-calling loop, temp 0; DeepSeek/GPT/Claude)
│   ├── router.py                # code-assigned behaviour: tool log -> Decision
│   ├── llm_parser.py            # semantic message parsing (JSON extraction), vs the rule splitter
│   ├── prompts/dispatcher.txt   # system prompt, dispatcher persona (Streamlit desk)
│   ├── prompts/group.txt        # system prompt, group-chat persona (Telegram bot)
│   ├── state.py                 # DeskState: chat-side queues (1 Apr snapshot, commits only)
│   ├── audit.py                 # AuditLog: transactional allocation ledger
│   ├── storage.py               # SQLite locally / pooled PostgreSQL when DISPATCH_DATABASE_URL is set
│   ├── budget.py                # shared API-call budgets (per hour/day)
│   ├── confirmation.py          # follow-up intent parsing (confirm/cancel/modify)
│   └── desk.py                  # DispatchDesk: handle_message() -> Decision, confirm() -> record
├── adapter/                   # Telegram bot shell around DispatchDesk
│   ├── session.py             # per-chat session: trigger filter + confirmation gate (pure, tested)
│   ├── telegram_bot.py        # python-telegram-bot wiring; zero business logic
│   └── charts.py              # /queue bar-chart photos (matplotlib, headless)
├── database/
│   └── supabase_schema.sql    # shared PostgreSQL schema (5 tables, RLS on)
├── scripts/
│   └── check_database.py      # read-only shared-DB connectivity check
├── app/
│   ├── streamlit_app.py       # entry: auth gate, get_desk, confirmation-flow core, main()
│   ├── theme/                 # design system: tokens (palette/badges), icons, styles (CSS), motion (scroll sync)
│   ├── components/            # leaf renderers: cards + queue bars, LLM parse view, ledger cache
│   ├── tabs/
│   │   ├── desk/              # Desk tab: intake (4 sources) -> dispatch loop -> worklist; cards; scenario preview
│   │   ├── dashboard.py       # queue timeline, allocator lens, capacity drift, objective map
│   │   └── records.py         # ledger view + demo reset
│   ├── rail/                  # right rail: world & shock, objective picker, live queues (5s fragment refresh)
│   ├── sidebar/               # chat log + returned-batch recorder
│   └── local_auth/            # remember-me localStorage component
├── eval/
│   ├── run_eval.py              # batch runner: inbox -> JSONL of Decisions (+ latency)
│   ├── score_run.py             # scores a run vs labels: behaviour / workshop / faithfulness
│   ├── replay_offline.py        # re-scores recorded runs on the current code, no API key
│   ├── shock.py                 # periodic shock calendar + shock-aware labels
│   └── faithfulness.py          # every number in the reply must trace to the tool log
├── results/                   # committed eval artefacts (inbox_*/heldout_* runs + scores)
├── tests/                     # pytest suite: one failure case per feature (289 tests)
└── pyproject.toml             # uv project, Python 3.11
```

## Sprint 3 — realism, polish, and one shared ledger

Key milestones since Oct 30, in the order they landed:

- **Splits and review fixes** ([Claude](https://claude.com) · [SishuoZhou](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/SishuoZhou)),
  [#20](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/20)):
  orders no single workshop can finish get ranked multi-workshop split
  options ([docs/SPLITS.md](docs/SPLITS.md)); the held-out review's three
  desk problems (lookup filters, recommendation consistency) fixed.
- **The UI grew up** ([Zhangruikai](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/Zhangruikai-rzha0162)): hybrid became the default objective,
  candidate cards got live queue bars and entrance animations, the dashboard
  gained queue timeline / allocator lens / capacity drift views, and the
  world clock made the Apr-1 demo ↔ Jan-1 replay switchable with a seeded
  shock trigger ([desk/config.py](desk/config.py)).
- **Full-scale timeline evaluation** ([Zhangruikai](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/Zhangruikai-rzha0162)): all 120 F-series
  requests replayed on the world clock with periodic shock windows and
  shock-aware labels
  ([notebooks/full120_timeline_shock.ipynb](notebooks/full120_timeline_shock.ipynb),
  [eval/shock.py](eval/shock.py)).
- **One-tap dispatching** ([Claude](https://claude.com) · [SishuoZhou](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/SishuoZhou),
  [#21](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/21)–[#35](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/35)):
  cards became the confirm buttons, the page scrolls to the next open order
  after each commit, already-committed orders mark themselves, and the LLM
  parser became an inbox tab with field-level register checks.
- **A more honest world** ([GuanmingYang](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/beibei323)),
  [#36](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/36)):
  the scenario preview prices Sunday closures, extra transport days and
  seeded capacity noise against the baseline ranking
  ([app/tabs/desk/scenario.py](app/tabs/desk/scenario.py)).
- **One shared ledger** ([RuoxiZhou](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/chikD666)),
  [#38](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/38)):
  web and bot can share one Supabase PostgreSQL ledger — advisory-lock
  serialised writers, duplicates refused by the database itself
  ([docs/SHARED_DATABASE.md](docs/SHARED_DATABASE.md),
  [scripts/check_database.py](scripts/check_database.py)).
- **Planning, validation and testing** ([Xuehann](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/Xuehann) · [XuantingWang](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/ADEdreambridge)): sprint
  planning and task coordination, acceptance checks on the shared-ledger
  rollout and the UI changes, and the demo test passes that caught the
  rough edges before they shipped.
- **Latency hunt and operations** ([kimi](kimi.moonshot.cn/),
  [#37](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/37)–[#46](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/46)):
  the flat 2,100-line app/ layer reorganised by surface; bot proposals
  survive restarts and confirm via one-tap buttons or "yes all", with
  `/queue` chart photos; pooled connections, a version-gated ledger cache,
  pipelined transactions and a longer LLM timeout fixed the cross-border
  lag; batch confirm for the web worklist; and a local sandbox by default
  with Reset & connect to shared DB on the Records tab.

## Safety and deployment

See [deployment and migration notes](docs/DEPLOYMENT.md) before upgrading.
The model tools are read-only. Human confirmation uses a transactional
allocation ledger; follow-ups update the pending proposal. Public
Streamlit deployments require `APP_PASSWORD`, and every provider requires its
own key (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Server-side
API call budgets survive new sessions and Reset demo.

Storage modes: the Streamlit app starts in a **local sandbox** (session-local
SQLite; nothing touches shared data — safe for debugging and tests), and the
Records tab's **Reset & connect to shared DB** rebuilds the desk on the shared
Supabase ledger, the same one the Telegram bot always uses. With no cloud
database configured, everything falls back to local SQLite; a configured-but-
unreachable cloud database fails loudly instead of silently writing locally.
Existing JSONL audit records are imported once (duplicates skipped, first
record wins).

## Quick Start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Copy `.env.example`
to `.env` and fill in `DEEPSEEK_API_KEY` (the chat smoke test and the UI's
dispatching need it) and `APP_PASSWORD` (the UI asks for it). The simulator,
benchmarks and tests run without any key. Never commit `.env`.

```bash
cp .env.example .env                        # then edit the values
uv sync                                     # install deps (generates uv.lock)
python harness/simulate.py                  # runs the three baselines (random / greedy_biggest / cheapest)
python harness/eft_benchmark.py --seeds 10  # EFT benchmark, normal + shock, averaged over 10 seeds
uv run pytest                               # tool unit tests (incl. failure cases)
uv run python desk/agent.py "R07: ORD-063 — 100 cardigans, make Apr 29."   # chat smoke test (needs DeepSeek key in .env)
uv run streamlit run app/streamlit_app.py   # the dispatcher UI
```

`harness/simulate.py` loads its data from `../data` — keep the `harness/` and `data/` directories as siblings.

## Team Members

-
