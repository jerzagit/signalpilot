# Running and verifying SignalPilot

Run PowerShell commands from the repository root. Use the existing `.venv`.
Do not print `.env`, Telegram session contents, or credentials into reports.

## Inspect before starting anything

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match '^python(w)?\.exe$' } |
  Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine |
  Format-List
Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, OwningProcess
Get-Content data/bot.pid, data/dashboard.pid -ErrorAction SilentlyContinue
```

Match the executable/command line to THIS checkout and the service entry point.
A `.venv\Scripts\python.exe` launcher and its underlying Python child are one
service; the actual listener/PID file normally refers to the child. PID files
can be stale. Never terminate a process based on a PID file alone.

On Windows, named mutexes `SignalPilotV1.bot` and `SignalPilotV1.dashboard` are
the authoritative singleton guards. On other platforms the implementation uses
exclusive PID-file creation. Do not remove guards to force a second instance.
The mutex names are shared across checkouts; another checkout may already own one.

## Start only a missing service

After confirming the service is absent, run the applicable command, not both
automatically. The working directory must remain the repository root.

```powershell
$projectRoot = (Get-Location).Path
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'logs') -Force | Out-Null
```

Bot startup connects to Telegram, may notify admins, and may execute configured
auto-trading. Use only within an authorized request to operate the bot; it is not
a test or a necessary step for dashboard development.

```powershell
Start-Process -FilePath $projectPython -ArgumentList 'bot.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput 'logs/bot_stdout.log' -RedirectStandardError 'logs/bot_stderr.log'
```

Dashboard:

```powershell
Start-Process -FilePath $projectPython -ArgumentList 'dashboard\app.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput 'logs/dash_stdout.log' -RedirectStandardError 'logs/dash_stderr.log'
```

Capture old console logs first if needed; these launch paths reuse log files.
First-time Telegram login may require an interactive terminal. Do not delete
existing session files to work around login issues. Dependencies are listed in
`requirements.txt`; trading additionally imports `MetaTrader5`, which is not
currently declared there. The installed terminal and integration are required
for trading. Do not enable trading or install/upgrade packages merely to check UI.

## Stop or restart

Prefer Ctrl+C in the service's original terminal when available. For a hidden
process, re-inspect its command line and parent relationship immediately before
using `Stop-Process -Id <verified-service-pid>`. Confirm it exited, then use the
appropriate start command. Never terminate every Python or MT5 process.

The Flask entry point runs with `debug=False`; code and cached template changes
require a dashboard restart. Restarting the dashboard does not require restarting
the bot. Stopping the bot interrupts monitoring; it does not itself close broker
positions. Preserve `data/` through restarts.

## Health checks

```powershell
foreach ($route in @('/', '/trades', '/api/stats', '/api/grouped')) {
    $response = Invoke-WebRequest -Uri ('http://127.0.0.1:5001' + $route) -UseBasicParsing
    '{0}: HTTP {1}' -f $route, $response.StatusCode
}
Get-Content logs/bot.log -Tail 20
```

Inspect logs locally and summarize rather than copying private content into
documentation. Look for successful listener startup, recent polling or message
activity, and repeated connection/manager errors. A live PID or HTTP 200 alone
does not establish successful trading. Avoid `/api/account` for a purely
database-backed check: it can initialize the MT5 integration.

For UI changes, check the actual browser behavior, including empty/error states
where relevant. For dates, check presets, custom ranges, inclusive end dates,
invalid ranges, and reload persistence.

## Tests and dependencies

Known bounded checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_geom5_parser.py tests/test_followup_parser.py tests/test_forwarder.py tests/test_card_image.py -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Baseline on 2026-09-25: these 30 tests passed and dependency consistency passed.
That is historical evidence, not a substitute for rerunning relevant checks.

Do not blindly run the full suite against the active checkout's runtime state:

- `tests/test_news.py::test_rss_poll_ingests_only_matching` clears and rewrites
  the configured news buffer/seen files. Patch both paths to `tmp_path` first.
- `tests/test_autotrade.py` mocks some MT5 calls and trade JSON, but `_manage`
  can still invoke admin notification, database synchronization, and exit writes.
  Isolate these boundaries before executing those tests.
- For new tests, patch MT5 connection/order APIs, Telegram delivery, all state
  paths, and `core.db.DB_PATH` as appropriate. Do not use live credentials/data.

No end-to-end live trading test was performed as part of setting up this workflow.
