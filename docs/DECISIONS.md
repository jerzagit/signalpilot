# Project decisions and conventions

Recorded 2026-09-25 from inspected code and the user's requested workflow.
Existing implementation choices below are observations; their original authors'
rationale is not assumed. Add dated entries when a decision changes.

## Persistent project guidance

Use root `AGENTS.md` as a short entry point, with task-specific documentation
under `docs/`. Keep feature records with implementation and verification evidence.
Reason: preserve useful project knowledge between sessions without requiring
agents to reread every document. Code remains the authority on actual behavior.

## Independent service lifecycle

The bot and Flask dashboard are separate services, guarded by named Windows
mutexes. Reuse running instances, distinguish launcher/child pairs, and restart
only the affected service. This follows the user's explicit no-duplicates rule
and avoids unnecessary interruption to the listener/manager.

## Reporting data and date semantics

The dashboard uses the SQLite deal mirror for reports; live account probing is
a separate route. Grouped-trade filters select signals by `received_at` with an
exclusive next-midnight upper bound. Daily P&L uses deal dates. Preserve this
distinction unless a feature explicitly changes it and updates its UI wording.

## Configuration and runtime state

Configuration comes from environment variables loaded through python-dotenv.
Runtime data and sessions stay outside version control. Documentation records
variable names and behavior, not actual credentials, account details, or balances.

## Verification boundary

Development tests use temporary state and mocked delivery/trading integrations.
Starting the bot is an operational action, not a smoke test. Existing test
isolation gaps are tracked in the runbook; successful bounded tests must not be
reported as a full suite pass or proof of live execution correctness.
