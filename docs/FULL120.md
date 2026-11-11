# Full-120 timeline evaluation (rerun 11 Nov 2026)

[← back to README](../README.md)

All 120 requests in `data/dispatch_requests_full120.txt`, replayed in
`[Sent: ...]` order from 1 Jan as one timeline: stages on, periodic shocks
(one active workshop closed 14 days every other week, seed 5105), queues
drain with time and grow with every allocation. Code: `main` @ `e61d50d`;
model: OpenAI GPT 6 Luna; labels: `data/f_heldout.json` (unchanged).

| Metric | Result |
|---|---|
| Behaviour accuracy | **93/120 = 0.775** (0 API errors) |
| Mean latency | 7.5 s per request |
| Earlier notebook runs, for reference | 88/120 (GPT, 3 Nov; DeepSeek, 10 Nov) |

| Request kind | Correct | | Request kind | Correct |
|---|---|---|---|---|
| ambiguous | 16/16 | | missing | 11/12 |
| ineligible | 16/16 | | impossible | **1/12** |
| complete | 27/28 | | unanswerable | **0/12** |
| constraint | 22/24 | | **total** | **93/120** |

23 of the 27 errors come from two kinds of request.

**1. Requests that change the order's completion date (impossible, 11 of 12 wrong).**
Each says the customer has moved delivery to the dispatch day itself, for
example F061: *"New delivery deadline is Feb 13, exactly the day we send it
out. We used to have until Mar 14."* No workshop can deliver the same day,
so the label is `impossible`. But the desk always takes the due date from
the order register. The model notices the conflict and says so ("the
register still has ORD-032 due Mar 14"), then checks feasibility against the
**old** date, which is easy to meet. Result: `allocate` 8 times, `ask` 3
times. Fix: add `due_date` to the parsed request and pass a deadline stated
in the message to `rank_candidates` / `earliest_feasible`, recording "deadline
from message, register says X".

**2. Questions the data cannot answer (unanswerable, 12 of 12 wrong).**
Invoice status, deposit, buyer phone number, QC report and so on. The model's
reply is right every time (e.g. "the order lookup doesn't include deposit
details"), but the behaviour is assigned by `desk/router.py`, not by the
reply. Two things go wrong there. Every full-120 message ends with a
`[Sent: YYYY-MM-DD]` tag, and `"sent"` is in `_ALLOC_MARKERS`, so every
message looks like a dispatch request; and most of these questions ("how much
deposit", "what street address") match none of the short `_QUERY_MARKERS`
anyway. The result is `ask` (10), `allocate` (1, F032, after the model called
`rank_candidates`) or `answer` (1), never `no_data`. Fix: strip the envelope
tag before routing, and detect data questions by pattern (or a small
classifier) instead of a keyword list.

**The other 4 errors:** F039 and F084 tell the desk to exclude a workshop;
the router treats a named, ruled-out workshop as a refusal, while the label
expects an allocation to the remaining shops. F015 has no new date but was
ranked anyway (`ask` → `allocate`), and F095 read *"Factory is full"* as a
workshop name and asked which one was meant.

## Requests for orders that are already completed

86 of the 120 requests name an order that the register marks **COMPLETE**,
and every one of those orders was completed *after* the request's sent date:
the factory finished them in-house. The replay asks "what if they had been
sent outside on that day", so the runner first resets them to
`IN_PROGRESS`; otherwise the desk would correctly refuse to dispatch a
finished order.

At first sight the completed orders look like the problem:

| Order named in the request | Correct |
|---|---|
| COMPLETE in the register | 62/86 (0.72) |
| still open in the register | 31/34 (0.91) |

But all 12 *impossible* requests and 10 of the 12 *unanswerable* ones name a
completed order, so the gap is mostly which kinds of request fall in each
group. Within the other five kinds the two groups score the same: **61/64
(0.95)** for completed orders vs **31/32 (0.97)** for open ones. The
completed status itself, after the reset, is not what causes the errors;
the deadline changes and the routing tag above are. One side effect remains:
the reset clears the in-house completion but keeps the register's stage, so
some replies describe a finished order as "in progress at the WASHING
stage" (e.g. F095).

Reproduce: `python eval/run_full120.py` (add `--limit 10` for a smoke test;
needs `OPENAI_API_KEY`). Output in `results/full120/`:
`full120_rerun_20261111_openai.jsonl` (decisions and tool logs),
`..._scores.json` (all numbers, one row per request) and `..._summary.md`.
Compared with the notebook, the script raises the API budget so a full run
does not stop part-way, rebuilds queues when resumed, uses a fresh ledger,
and keeps OldMill suspended instead of re-opening it every day.
