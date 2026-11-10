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
├── docs/                      # ALLOCATOR (algorithm) · EVALUATION (routing, faithfulness) · DEPLOYMENT
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
│   └── faithfulness.py          # every number in the reply must trace to the tool log
├── results/                   # committed eval artefacts (inbox_*/heldout_* runs + scores)
├── tests/                     # pytest suite: one failure case per feature (267 tests)
└── pyproject.toml             # uv project, Python 3.11
```

## Sprint 3 — realism, polish, and one shared ledger

What shipped after Sprint 2, told as the problems we hit:

- **A more honest world.** The desk gained a switchable world clock (Apr-1
  demo ↔ Jan-1 full replay), stages mode, and a seeded shock trigger — close
  a workshop and eligibility, ranking and risk flags all react
  ([desk/config.py](desk/config.py), [eval/shock.py](eval/shock.py)). The
  scenario preview prices Sunday closures, extra transport days and seeded
  capacity noise against the baseline ranking
  ([app/tabs/desk/scenario.py](app/tabs/desk/scenario.py),
  [#36](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/36)).
- **Full-scale timeline evaluation.** All 120 F-series requests replayed
  against the world clock with periodic shock windows and shock-aware labels
  ([notebooks/full120_timeline_shock.ipynb](notebooks/full120_timeline_shock.ipynb));
  held-out behaviour/faithfulness scoring stayed the gate
  ([docs/EVALUATION.md](docs/EVALUATION.md)).
- **The UI grew up.** Cards became the confirm buttons, the page scrolls to
  the next open order after each commit, already-committed orders mark
  themselves, the LLM parser became an inbox tab with field-level register
  checks, and learned capacity flows through every estimate
  ([#21](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/21)–[#36](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/36)).
  Then the 2,100-line flat app/ layer was reorganised by surface (theme /
  components / tabs / rail / sidebar), zero behaviour change
  ([#37](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/37)).
- **Two front-ends, two ledgers.** The hosted web app and the Telegram bot
  each kept their own SQLite file — a commit on one was invisible to the
  other. Both can now share one Supabase PostgreSQL ledger
  ([docs/SHARED_DATABASE.md](docs/SHARED_DATABASE.md),
  [#38](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/38)):
  advisory-lock serialised writers, duplicate orders refused by the database
  itself, plus a read-only [connectivity check](scripts/check_database.py).
- **The bot's "yes" didn't commit.** Pending proposals lived in process
  memory; a free-tier restart (or an answer-without-rerank follow-up) dropped
  them, and a lone yes fell into a fresh conversation. The adapter now
  answers yes-with-nothing-pending deterministically, keeps proposals alive
  across answer-only follow-ups, tracks them per order, and adds one-tap
  commit buttons plus a `/queue` chart photo
  ([#39](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/39)).
- **Every click felt frozen.** Sharing a cross-border database made each
  click pay several connection handshakes, and the UI re-read the whole
  ledger once per card. Three stacked fixes: pooled connections
  ([#40](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/40)),
  a version-gated ledger cache (dozens of reads per rerun → one cheap
  version check,
  [#41](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/41)),
  and pipelined transactions
  ([#43](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/43)).
  The all-"Request failed" dispatch wave was a hard-coded 30 s LLM timeout
  with no retries — now 120 s with retries
  ([#42](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/42)).
- **Twenty cards, twenty clicks.** Batch confirm: a Confirm-all button in
  the web worklist and "yes all" in the bot — every order still passes the
  full per-order validation chain
  ([#44](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/44)).
- **Debugging shouldn't touch production data.** The web app starts in a
  local sandbox; the Records tab carries Reset & connect to shared DB for
  when the two front-ends should share state
  ([#45](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/45)).

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

```bash
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
