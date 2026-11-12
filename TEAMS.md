# Team 6 — Member Contributions

**DSS5105 Capstone 2026 · Track 2: The Quick-Response Subcontracting Desk**

Live system: [Streamlit web app](https://dss5105-capstone-2026-team6-yrcuaguw78h57dg9dc4pmi.streamlit.app) · [Telegram bot](https://t.me/Ddispatcherr_bot) · [Repository](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6)

*Note: any link (a `#` number or a file name) opens the corresponding delivery record in the repository when clicked.*

## 1. Deliverables

| Deliverable | Owner |
|---|---|
| EVALUATION.pdf (evaluation report) | Yang Guanming |
| DOCUMENTATION.pdf (documentation report) | Zhou Sishuo |
| Strategic_Recommendations.pdf (industry analysis) | Research & fact-checking: Zhang Ruikai · Zhou Sishuo · Dang Xuehan — Writing: Wang Xuanting · Yang Guanming · Zhuang Ruoxi |
| Sprint 2 demo video | Zhang Ruikai |
| PPT & video production · Sprint 3 demo video narration | Wang Xuanting · Dang Xuehan · Zhuang Ruoxi |

## 2. Individual responsibilities

| Member | GitHub | Responsibility |
|---|---|---|
| Dang Xuehan | [Xuehann](https://github.com/Xuehann) | Project leadership: planning, coordination, dispatch safety, documentation, acceptance |
| Wang Xuanting | [ADEdreambridge](https://github.com/ADEdreambridge) | Robustness: duplicate handling, refusal alternatives, failure analysis |
| Yang Guanming | [beibei323](https://github.com/beibei323) | Scenario preview (production calendar realism) · full-120 request set production & validation · evaluation report |
| Zhang Ruikai | [Zhangruikai-rzha0162](https://github.com/Zhangruikai-rzha0162) | Foundation & operations lead: tool layer, routing, allocator, evaluation, full-stack changes, deployment ops |
| Zhou Sishuo | [SishuoZhou](https://github.com/SishuoZhou) | Split-order engine, one-tap dispatching UX, PR review & integration |
| Zhuang Ruoxi | [chikD666](https://github.com/chikD666) | Shared database: Supabase PostgreSQL ledger for web + bot |

## 3. Contribution percentages

Self-assessed by the team against the commit history (288 commits) and the
PR record (69 PRs). AI pair-programming tools ([kimi](https://kimi.moonshot.cn/),
[Claude](https://claude.com)) were used by members across the group and are
not counted as members.

| Member | Share | Basis |
|---|---|---|
| Dang Xuehan | 17% | dispatch-safety PRs (#12/#14/#16), documentation pass (#63–#68), planning and acceptance |
| Wang Xuanting | 14% | duplicate Skip, refusal alternatives, failure analysis + re-scoring (#56/#57) |
| Yang Guanming | 16% | scenario preview end to end (#21/#36/#53–#55) |
| Zhang Ruikai | 20% | 150+ commits — tool layer, routing v2.1, eval harness, tolerance allocator, UI overhaul, timeline evaluation, front/back-end changes, deployment & operations |
| Zhou Sishuo | 20% | split engine, one-tap UX, review & integration of the squad's PRs |
| Zhuang Ruoxi | 13% | shared Supabase ledger: schema, storage adapter, acceptance suite (#38) |

## 4. Specific tasks completed

**Dang Xuehan** — dispatch-safety hardening: read-only tools behind one human-confirmation endpoint, transactional ledger with duplicate protection, API budgets, password gate ([#12](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/12), [#14](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/14), [#16](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/16)) · assessor-facing documentation pass ([#63](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/63)–[#68](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/68)) · sprint planning, coordination, acceptance sign-off.

**Wang Xuanting** — one-tap Skip for duplicate orders on both Streamlit and the Telegram bot · code-ranked alternatives for refusals (R24) · failure analysis with offline re-scoring → workshop accuracy 0.842→0.895 dev, 0.692→0.846 held-out · Streamlit deploy hotfix ([#47](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/47), [#52](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/52), [#56](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/56), [#57](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/57), [FAILURE_ANALYSIS](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/FAILURE_ANALYSIS.md)).

**Yang Guanming** — scenario preview end to end: Sunday closures, transport delay, seeded capacity noise, selectable start dates, preview dialog ([#21](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/21), [#36](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/36), [#53](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/53)–[#55](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/55), [scenario.py](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/app/tabs/desk/scenario.py)) · produced and validated the full-120 request set used for the timeline evaluation — drafting the messages, checking every request against the order register, and verifying the replay results ([FULL120](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/FULL120.md)).

**Zhang Ruikai** — original Streamlit UI ([#1](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/1)/[#2](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/2)) · agent tool layer · routing v2.1 intent rules · offline eval harness ([run_eval](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/eval/run_eval.py), [faithfulness](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/eval/faithfulness.py)) · tolerance-plateau allocator and its 2×2 scan ([Tolerance_Scan](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/Tolerance_Scan.md)) · UI overhaul (switchable objective panel, live queue bars, dashboard) · world clock + shock trigger + LLM parser backend · two front-end restructures (Oct 29 module split; [#37](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/37)) · 120-request timeline evaluation ([notebook](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/notebooks/full120_timeline_shock.ipynb), [FULL120](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/FULL120.md)) · bot hardening: proposal persistence, one-tap buttons, /queue charts, yes all ([#39](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/39)) · database performance: connection pooling, version-gated cache, pipelined transactions ([#40](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/40)/[#41](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/41)/[#43](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/43)) · batch confirm ([#44](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/44)) · sandbox-by-default mode ([#45](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/45)) · scenario preview popover pinned to the work area ([#60](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/60)) · deployment & operations: Render bot hosting, Streamlit Cloud, keep-alive, LLM timeout tuning ([#42](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/42)).

**Zhou Sishuo** — multi-workshop split ranking for impossible orders ([SPLITS](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/SPLITS.md)) · held-out review fixes (lookup filters, recommendation consistency) · cards as confirm buttons with live queue bars · auto-scroll to the next open order · committed-order marking · LLM parser tab with Parse → Dispatch · returned-batch recorder fixes · learned-capacity rollout across estimates · earlier fixes: GPT provider config, password gate, dashboard queue chart, case-filter counts, chat-log scroll sync · full-120 rerun report · team integrator: reviewed and merged most of the squad's PRs — PRs [#3](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/3)–[#6](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/6), [#8](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/8)–[#11](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/11), [#13](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/13), [#15](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/15), [#20](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/20)–[#35](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/35), [#62](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/62).

**Zhuang Ruoxi** — designed, built and deployed the shared Supabase PostgreSQL ledger: schema with RLS, storage adapter with advisory-lock serialised writers, acceptance suite including a real Telegram round-trip ([#38](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/38), [SHARED_DATABASE](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/docs/SHARED_DATABASE.md), [check_database.py](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/blob/main/scripts/check_database.py)).

## 5. Collaboration dynamics

- **Feature branches + PR review.** All work landed through pull requests,
  with a rotating reviewer/integrator role for merges. The single shared
  production branch is `main`.
- **AI pair programming, declared.** The commit history includes two AI
  pair programmers as committers; every AI-written change passed the same
  human review and the 283-test offline suite.
- **Shared infrastructure ownership.** The shared database contract
  (schema, acceptance) and the deployment/operations channel (bot hosting,
  web hosting, keep-alive) are owned by different members — a hand-off
  validated by the two-front-end demo.
- **Conflict handling by evidence.** Disagreements were settled on
  measurements, not preference — e.g. the allocator objective was chosen by
  a 2×2 tolerance scan (normal/shock × default/stages), and a premature
  scenario-dialog change was reverted and re-landed with tests
  ([#53](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/53)→[#54](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/54)→[#55](https://github.com/DSS5105-Capstone-2026-Team6/DSS5105-Capstone-2026-Team6/pull/55)).
- **Failure-driven iteration.** The held-out failure log was re-scored
  after every fix round; the repeat-offender case (R24) became a feature
  (refusal alternatives) instead of a patch.
