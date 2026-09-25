# Working on SignalPilotV1

SignalPilot is a Python Telegram signal listener with optional MT5 execution,
news context, and a Flask dashboard. Work from the repository root using
`.venv\Scripts\python.exe`; relative `data/` and `logs/` paths depend on it.

## Read only what the task needs

- Module ownership, data flow, or database changes: [architecture](docs/ARCHITECTURE.md).
- Starting, stopping, restarting, or checking services: [runbook](docs/RUNBOOK.md).
- New features and substantial fixes: [feature workflow](docs/WORKFLOW.md).
- Why an existing convention exists: [decisions](docs/DECISIONS.md).
- Continuing unfinished work: the relevant record in `docs/features/`.

Verify relevant code against documentation; do not reread the whole repository
for each change. Update inaccurate guidance as part of the same task.

## Working rules

- Inspect `git status --short` before editing. Preserve unrelated local edits;
  do not reset, clean, overwrite, or commit them as part of your change.
- Before launching services, inspect current process command lines, parent/child
  relationships, port 5001, and the singleton guards. Reuse healthy instances.
  A virtual-environment launcher plus its Python child is one service instance.
- Restart only the service affected by an authorized change. Do not restart the
  trading bot for a dashboard-only change. Never kill all Python processes.
- Keep `.env`, credentials, Telegram sessions, account identifiers, live data,
  and log contents out of committed documentation and test fixtures.
- Tests must not place orders, send Telegram messages, or modify runtime data.
  Use temporary state/database paths and mocks at all external boundaries.
  See the runbook before running the full existing test suite.
- Do not run `scripts/` utilities as generic smoke tests: some publish messages,
  alter channel membership, or open/reopen trades. Read the particular script
  and confirm its behavior is within the user's request first.
- Do not change trading settings or enable auto-trading as a side effect of a
  UI, documentation, or test task.
- For features, record acceptance criteria, implementation, validation, and
  unfinished work using `docs/features/_template.md`. Small fixes can use a
  short record; documentation should stay proportional to the task.
- Completion means relevant checks passed, requested behavior was verified,
  and affected project guidance and the feature record are current. Report
  checks not run and known limitations honestly.

## Quick verification

Known bounded checks, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_geom5_parser.py tests/test_followup_parser.py tests/test_forwarder.py tests/test_card_image.py -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

These checks do not establish correctness of MT5 execution, the entire test
suite, or new dashboard behavior. Choose additional checks for the actual change.
