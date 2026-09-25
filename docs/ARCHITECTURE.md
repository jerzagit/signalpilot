# SignalPilot architecture

Baseline inspected: 2026-09-25. This map describes the inspected working tree,
including pre-existing uncommitted changes. It is not a full correctness audit.

## Service and data flow

```text
bot.py -> core/listener.py -> Telegram source messages
                             |-> parsers -> Signal / FollowUpAlert
                             |      |-> optional autotrade -> local MT5 terminal
                             |      |                       -> JSON + SQLite
                             |      |-> cards / optional chart -> Telegram output
                             |-> news sources -> headline cache
RSS feeds -> core/rss_news.py -> core/news.py -> signal-card context

dashboard/app.py -> core/db.py -> data/trades.db -> calendar / grouped trades
                -> optional MT5 account probe (/api/account)
```

The bot and dashboard are separate processes. The bot starts the listener and
optional background news/trading tasks; the dashboard listens on
`127.0.0.1:5001`. Each entry point uses `core/singleton.py`.

## Where to make changes

| Concern | Primary files | Notes |
| --- | --- | --- |
| Startup and retry | `bot.py`, `core/singleton.py` | Bot retry loop; independent bot/dashboard guards |
| Configuration | `core/config.py` | Environment-based values, source profiles, trading/news switches |
| Telegram routing | `core/listener.py` | Resolves sources, attaches previous-signal context, forwards results |
| Signal types/parsing | `core/signal.py`, `core/parsers/` | Registry selects `geom5` or `default`/`flexible`; unknown profile returns no signal |
| Trading | `core/autotrade.py` | Entry, layers, follow-up exits, price exits, breakeven, MT5 sync |
| Persistence/reporting | `core/db.py` | SQLite schema, deal ingestion, grouping, realized P&L |
| Message delivery | `core/forwarder.py` | Card text and actual Telegram HTTP calls are separate functions |
| Visual cards/charts | `core/card_image.py`, `core/grabshot.py` | Generated cards and Windows chart capture |
| News | `core/news.py`, `core/rss_news.py` | Filtering, persistent deduplication, cached context, RSS polling |
| Dashboard | `dashboard/app.py`, `dashboard/templates/`, `dashboard/static/` | Flask routes, Jinja templates, inline scripts and CSS |

## Runtime data

Paths are relative to the process working directory; always start from the root.

| Path | Role |
| --- | --- |
| `data/session*` | Telethon authentication/session state; private |
| `data/last_signals.json` | Last symbol/direction per source for follow-up context |
| `data/autotrades.json` | Trading state keyed by source and signal tag |
| `data/trades.db` | Dashboard SQLite mirror, with WAL sidecar files |
| `data/news_buffer.json`, `data/news_seen.json` | Persistent news context and deduplication |
| `data/cards/`, `data/screenshots/` | Generated images |
| `data/bot.pid`, `data/dashboard.pid` | Diagnostic PIDs, not authoritative Windows locks |
| `logs/bot.log` | Bot application log; other console logs depend on launch method |

SQLite contains `signals` (keyed by signal tag), `trades` (unique deal ticket,
position ID, tag, timestamps, prices and P&L components), and `meta` (sync state).
`init_db()` creates tables and currently adds the missing `signals.exit` column.
Do not assume a general migration framework exists.

## Dashboard semantics

- `/`: calendar with daily realized P&L and equity curve.
- `/trades`: grouped signals; `/api/grouped` returns their layers and closes.
- `/api/calendar`, `/api/trades`, `/api/stats`: reporting endpoints.
- `/api/account`: optional live MT5 probe, with a database-derived fallback.
- Grouped date filtering uses signal `received_at`, not each close's timestamp.
  The selected To date includes that day, with next midnight excluded.
- Calendar daily P&L uses deal timestamps and SQLite `localtime`.
- `_iso_to_ts()` currently uses server-local `time.mktime`, despite its UTC
  docstring. Browser formatting uses browser-local time. Verify timezone behavior
  if clients and server use different zones; no explicit timezone contract exists.
- Groups default to a limit of 50. The trades page's Total realized KPI is
  all-time `db.stats()` and does not change with the date filter.

## Trading boundaries and known documentation gaps

Trading state uses source + tag, but the SQLite signal primary key is tag alone.
Review this distinction before supporting colliding tags across providers.
Position helpers filter by bot magic and symbol; do not assume every exit is
isolated to a particular signal's tickets when multiple signals share a symbol.

`PRICE_TP_CLOSE` enables price-triggered exits in addition to Telegram follow-ups.
The manager also checks targets, applies breakeven, and synchronizes deals.
The existing [trading guide](AUTOTRADE.md) is historical: its message-only exit
description and account/balance examples are not authoritative current settings.
Use the code and privately configured environment when checking behavior.

Other follow-up items: duplicate `close_level` definitions in `core/db.py`;
duplicated date-bound helpers in `dashboard/app.py`; full-suite test isolation
gaps described in the runbook. These observations are not fixes or a complete
defect inventory.
