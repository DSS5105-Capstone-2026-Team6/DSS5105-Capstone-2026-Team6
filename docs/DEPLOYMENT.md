# Deployment, state and safety notes

## Optional shared PostgreSQL ledger

The shared-database extension is documented in [SHARED_DATABASE.md](SHARED_DATABASE.md).
With `DISPATCH_DATABASE_URL` configured, allocations, learned performance and
API usage use PostgreSQL instead of the host-local SQLite file described below.
Both Streamlit and Telegram must run the updated code and use the same database
settings. Existing SQLite records are not automatically imported into PostgreSQL.
Two local processes (web + bot) sharing the Supabase ledger passed on 10 Nov
2026; the end-to-end check of the two live deployments together is still open
(see the acceptance record in SHARED_DATABASE.md).

## Validate a checkout

From a clean checkout:

```bash
uv sync
uv run pytest -q
```

There is also a network-free regression suite that uses only Python's standard library:

```bash
python -m unittest discover -s tests -p test_dispatch_safety.py -v
```

No regression test needs a real API key; the cloud ledger tests in
`tests/test_shared_postgres.py` are skipped unless `DSS5105_RUN_CLOUD_TESTS=1`
and database credentials are set. GitHub Actions (`.github/workflows/tests.yml`)
runs the same pytest suite on Python 3.11 and 3.12 on every push and pull
request.

## Streamlit configuration

In the deployed app's Settings → Secrets, configure at least:

```toml
DEEPSEEK_API_KEY = "<your DeepSeek key>"
APP_PASSWORD = "<a long random password>"
```

Use `OPENAI_API_KEY` only for OpenAI, and `ANTHROPIC_API_KEY` only for Anthropic.
If the DeepSeek key was previously stored as `OPENAI_API_KEY`, rename that
secret to `DEEPSEEK_API_KEY` before restarting the updated app. Never send keys
in chat or commit them to GitHub.

The app now refuses access without `APP_PASSWORD`. Local-only developers may
explicitly set `REQUIRE_APP_PASSWORD="false"`; keep the default on public deployments.
Locally, copy `.env.example` to `.env` and replace the placeholder values.

Optional root-level secrets/environment variables (all values shown as strings):

```toml
API_CALLS_PER_HOUR = "200"
API_CALLS_PER_DAY = "1000"
MAX_INPUT_CHARS = "8000"
MAX_OUTPUT_TOKENS = "2048"
```

Limits count actual model API attempts, including tool-loop rounds and semantic
follow-up classification. They are global to the SQLite file and survive new
browser sessions and Reset demo. They are not currency spending caps; keep an
appropriate provider-side budget as well. Failed model requests consume one
reservation. Resetting/deleting the database also resets these counters.

## State and migration

- Default database: `results/audit_log.sqlite3`. Existing
  `results/audit_log.jsonl` records import transactionally once, and the original
  file is retained. Malformed or duplicate legacy records abort migration
  rather than silently discarding allocations.
- Back up an existing ledger before applying the update. SQLite is authoritative
  afterwards; new allocations are no longer appended to the old JSONL file.
- The Streamlit app starts every browser session in a **local sandbox**
  (session-local SQLite: its own ledger, learned performance and API budget).
  The Records tab's **Reset & connect to shared DB** switches that session to
  the shared ledger; **Disconnect** returns it to the sandbox. A model change or
  Desk rebuild does not reset queue state.
- Set `DISPATCH_DB_PATH` to an absolute path on a durable disk when one is
  available. Streamlit Community Cloud local files can disappear on redeploy or
  host replacement. This SQLite update does not provide durable cloud storage.
- Without `DISPATCH_DATABASE_URL`, the hosted Streamlit app and the Telegram
  bot (Render) keep separate local databases. Sharing state across hosts needs
  the shared PostgreSQL ledger (SHARED_DATABASE.md), not two hosts pointed at
  similar local paths.
- Reset demo affects all sessions on that database. It archives allocations
  transactionally and invalidates outstanding proposals; it leaves API usage
  and sign-in state intact.
- Evaluation runs use an isolated temporary allocation ledger, so operational
  commits do not change the fixture snapshot used for scoring.

## Telegram bot on Render

The bot runs as a free Render web service (`render.yaml`: `python -m adapter.telegram_bot`,
secrets set in the Render dashboard). It uses long polling: the process asks Telegram for
new messages, so Telegram traffic never reaches the service's URL. The service binds
`$PORT` and answers any GET with `dispatch bot alive`, only so Render accepts the deploy
and a monitor has something to ping.

- **Sleep.** Render's free tier stops a service after about 15 minutes without HTTP
  traffic. An UptimeRobot HTTP monitor pings `https://dispatcher-doubot.onrender.com`
  every 5 minutes to keep it awake.
- **What happens when the ping stops.** The bot sleeps and does not answer. It starts
  with `drop_pending_updates=True`, so messages sent while it slept are discarded on
  wake-up, not answered late. Seen on 11 Nov 2026: the service was asleep and showed
  Render's "service waking up" page.
- **Wake it by hand.** Open the URL above and wait for `dispatch bot alive`
  (30–60 seconds), then resend. Do this before a demo or a recording.
- **Check the monitor** in UptimeRobot if the bot keeps falling asleep: the monitor must
  be active, point at the URL above, and run at an interval under 15 minutes.
- **Always-on options** if this is not reliable enough: a paid Render instance, an
  always-on VM, or switching the bot to a Telegram webhook, where the incoming request
  wakes the service and Telegram retries deliveries that fail.

## Confirmation behavior

Buttons and familiar replies such as "yes", "好的", and "这单就给 W2 吧" take the
fast path without an extra model call. Other wording is interpreted by a
read-only API classifier. Questions, negations, conditions and changes are not
confirmations. Every commit checks the order, candidate, exclusions, eligibility
and queue version. Changed queues produce a fresh proposal and require review.

Follow-ups replace the decision cards and buttons. Existing exclusions survive
changes of objective and read-only questions; explicit additions/removals are
applied to the ranking context. Unknown constraints fail closed. Quantity and
due-date edits are deliberately not applied to the source CSV through chat:
they invalidate the proposal and ask for the register to be updated and the
desk/app restarted first.

Telegram option buttons are bound to a single response token, so clicking an
old message cannot confirm or modify a newer pending order.

## Validation boundary

The pytest suite runs offline: model calls are faked or replayed, so it checks
the desk, tools, ledger and UI logic, not live model behaviour. Live checks are
separate: the evaluation runs in `results/` (real DeepSeek calls, 28–29 Oct),
the local shared-ledger acceptance in SHARED_DATABASE.md, and manual checks of
the deployed app and bot. Before relying on a new provider or model, run
`eval/run_eval.py` against it.
