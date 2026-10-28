# Dispatch safety update

## Apply and validate

This change is based on main commit `ac3b96d78c26cb7c07a2f9346dd2bc9c393ae58a`.
If applying the supplied patch manually, run from a clean checkout of the repository:

```bash
git switch -c fix/dispatch-confirmation-and-shared-state
git apply --check dispatch-safety.patch
git apply dispatch-safety.patch
uv sync --group dev
uv run pytest -q
```

There is also a network-free regression suite that uses only Python's standard library:

```bash
python -m unittest discover -s tests -p test_dispatch_safety.py -v
```

No regression test needs a real API key. GitHub Actions runs pytest on Python
3.11 and 3.12 after the change is pushed; those jobs have not run as part of
local validation.

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
- All browser sessions in one deployment share queues and allocations. A model
  change or Desk rebuild no longer resets queue state.
- Set `DISPATCH_DB_PATH` to an absolute path on a durable disk when one is
  available. Streamlit Community Cloud local files can disappear on redeploy or
  host replacement. This SQLite update does not provide durable cloud storage.
- The hosted Streamlit app and a Telegram bot running on a separate PC still
  have separate databases. Sharing state across those hosts requires an
  external database/service, not pointing two hosts at similar local paths.
- Reset demo affects all sessions on that database. It archives allocations
  transactionally and invalidates outstanding proposals; it leaves API usage
  and sign-in state intact.
- Evaluation runs use an isolated temporary allocation ledger, so operational
  commits do not change the fixture snapshot used for scoring.

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

The local standard-library regression suite and syntax/patch checks run without
network calls. Existing pytest and real Streamlit/browser/provider integration
checks require dependencies not available in the execution environment. Verify
the deployed app and supported provider models in a staging session before
merging. This change has not been deployed and no real API key was used.
