# DSS5105 Capstone 2026 · Team 6

**Track 2: The Quick-Response Subcontracting Desk** — primary objective: **minimise lateness**.

[![tests](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/actions/workflows/tests.yml/badge.svg)](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-1971c2)
![tests](https://img.shields.io/badge/pytest-289%20passed-2b8a3e)

> The factory (SweaterCo) farms out batches to 8 outside workshops when it is full.
> This system answers the dispatcher's three questions for every incoming order —
> *can they make it, can they take it now, are they allowed to* — makes the
> allocation, and leaves an auditable record with the reasoning attached.

**Live** · [Streamlit App](https://dss5105-capstone-2026-team6-yrcuaguw78h57dg9dc4pmi.streamlit.app) · [Telegram Bot](https://t.me/Ddispatcherr_bot)
**Docs** · [Allocator](docs/ALLOCATOR.md) · [Evaluation](docs/EVALUATION.md) · [Deployment](docs/DEPLOYMENT.md) · [Shared DB](docs/SHARED_DATABASE.md) · [Splits](docs/SPLITS.md)

## Architecture

Two thin front-ends, one deterministic core, one ledger. The LLM only ever
emits JSON tool-call lists — every number comes from a tool.

```mermaid
flowchart LR
    TG["Dispatcher<br/>Telegram"]:::front
    WEB["Dispatcher<br/>Web browser"]:::front

    subgraph CLOUD["Hosting"]
        BOT["Telegram Bot<br/>adapter/<br/>long polling<br/>UptimeRobot keep-alive"]:::front
        UI["Streamlit App<br/>app/<br/>sandbox by default<br/>Reset and connect"]:::front
    end

    subgraph CORE["core package · desk — single source of truth"]
        DESK["DispatchDesk<br/>handle_message → Decision<br/>confirm → record"]:::core
        PARSER["llm_parser<br/>message → JSON<br/>orders · intent · constraints"]:::core
        AGENT["agent.py<br/>tool-calling loop · temp 0"]:::core
        TOOLS["tools.py · 10 tools<br/>lookup_order · check_eligibility<br/>get_queue · estimate_delivery<br/>rank_candidates · probe_overload<br/>earliest_feasible · split_options<br/>flag_at_risk · update_performance"]:::core
        ALLOC["allocator<br/>4 objectives<br/>lateness · defects · cost · hybrid"]:::core
        ROUTER["router<br/>tool log → behaviour<br/>allocate · refuse · impossible<br/>ask · answer · no_data"]:::core
        CONF["confirmation<br/>fast path yes or cancel<br/>API classifier · fail closed"]:::core
        AUDIT["audit<br/>transactional ledger<br/>UNIQUE order_id"]:::core
        PERF["performance<br/>returned batches →<br/>learned capacity"]:::core
        BUDGET["budget<br/>hourly · daily caps"]:::core
        STORE["storage<br/>SQLite or pooled PG<br/>pipeline · advisory lock"]:::core
    end

    LLM[("LLM APIs<br/>DeepSeek · GPT · Claude<br/>JSON tool calls only")]:::llm
    LITE[("Local SQLite<br/>sandbox · default")]:::store
    SUPA[("Supabase PostgreSQL<br/>shared ledger · RLS")]:::store

    TG --> BOT --> DESK
    WEB --> UI --> DESK
    DESK --> AGENT
    PARSER --> AGENT
    AGENT <--> LLM
    AGENT --> TOOLS --> ALLOC --> ROUTER --> CONF --> AUDIT
    TOOLS --> PERF
    AUDIT --> STORE
    PERF --> STORE
    BUDGET --> STORE
    STORE --> LITE
    STORE --> SUPA
    BOT <--> SUPA
    UI <--> SUPA

    click DESK "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/desk.py"
    click PARSER "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/llm_parser.py"
    click AGENT "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/agent.py"
    click TOOLS "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/tools.py"
    click ALLOC "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/ALLOCATOR.md"
    click ROUTER "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/router.py"
    click CONF "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/confirmation.py"
    click AUDIT "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/audit.py"
    click PERF "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/performance.py"
    click BUDGET "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/budget.py"
    click STORE "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/desk/storage.py"
    click BOT "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/adapter/telegram_bot.py"
    click UI "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/app/streamlit_app.py"
    click SUPA "https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/SHARED_DATABASE.md"

    classDef front fill:#d0ebff,stroke:#1971c2,stroke-width:1.5px,color:#1c2b3a
    classDef core fill:#f1f8fe,stroke:#339af0,stroke-width:1.5px,color:#1c2b3a
    classDef llm fill:#74c0fc,stroke:#1971c2,stroke-width:1.5px,color:#08263f
    classDef store fill:#339af0,stroke:#1971c2,stroke-width:1.5px,color:#ffffff
```

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

Key milestones since Oct 30 — who changed what, and what it bought us:

- **[SishuoZhou](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/SishuoZhou)** —
  owned the split-order engine and the one-tap dispatching UX:
  multi-workshop split ranking for impossible orders, the held-out review
  fixes (lookup filters, recommendation consistency), cards as confirm
  buttons and auto-scroll
  ([#20](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/20)–[#35](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/35),
  [docs/SPLITS.md](docs/SPLITS.md)) → far fewer clicks per order.
- **[GuanmingYang](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/beibei323)** —
  built the scenario preview end to end: Sunday closures, transport delay,
  seeded capacity noise, selectable start dates, and its own preview
  dialog ([#36](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/36),
  [#55](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/55))
  → ETAs that respect the real calendar.
- **[RuoxiZhou](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/chikD666)** —
  designed, built and deployed the shared Supabase PostgreSQL ledger:
  schema with RLS, the storage adapter with advisory-lock writers, and the
  acceptance suite incl. a real Telegram round-trip
  ([#38](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/38),
  [docs/SHARED_DATABASE.md](docs/SHARED_DATABASE.md))
  → both front-ends read and write the same truth.
- **[XuantingWang](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/ADEdreambridge)** —
  hardened the desk: a one-tap Skip for duplicate orders on both Streamlit
  and the Telegram bot, code-ranked alternatives for refusals (R24), the
  failure-analysis doc with offline re-scoring, and the Streamlit deploy
  hotfix
  ([#56](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/56),
  [#57](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/57),
  [docs/FAILURE_ANALYSIS.md](docs/FAILURE_ANALYSIS.md))
  → workshop accuracy after the fixes: 0.842 → 0.895 dev, 0.692 → 0.846
  held-out.
- **[Xuehann](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/Xuehann)** —
  sprint planning and project leadership: milestone planning and task
  allocation, cross-workstream coordination and progress tracking,
  validation and test passes on the shared-ledger rollout and the UI
  changes, acceptance sign-off before each merge, and demo-day
  presentation coordination.
- **[Zhangruikai](https://github.com/orgs/DSS5105-Capstone-2026-Team6/people/Zhangruikai-rzha0162)** —
  UI adjustments (switchable objective panel, live queue bars, dashboard
  views) and the 120-request timeline evaluation with periodic shocks
  ([notebooks/full120_timeline_shock.ipynb](notebooks/full120_timeline_shock.ipynb),
  [eval/shock.py](eval/shock.py)).
- **[kimi](kimi.moonshot.cn/)** —
  [#37](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/37),
  [#39](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/39)–[#46](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/46),
  [#60](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/60):
  app/ reorganised by surface; bot proposal fix, one-tap buttons, `/queue`
  charts, yes all; DB pooling + version-gated cache + pipelined
  transactions + longer LLM timeout; batch confirm; sandbox mode; scenario
  button pinned; deployed and operates the bot on Render.
- **[Claude](https://claude.com)** —
  used by members across the team: multi-workshop split ranking and the
  held-out review fixes (with SishuoZhou), one-tap cards and the parser
  tab, duplicate-skip and failure replay with XuantingWang, and
  implementation support across GuanmingYang's, RuoxiZhou's and Xuehann's
  tasks.

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
