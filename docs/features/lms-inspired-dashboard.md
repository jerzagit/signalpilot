# LMS-inspired dashboard redesign

Status: complete
Updated: 2026-09-25

## Goal and scope

Adapt the dark glass visual language of the local `lms-web-techpapa` project to
SignalPilot's Flask dashboard. Preserve SignalPilot's gold identity and all
Calendar, Trades, date-filter, target-label, and layer-expansion behavior.

## Acceptance criteria

- [x] Shared top navigation, dark glass surfaces, gold glow, and responsive menu.
- [x] Calendar KPIs, chart, calendar grid, and month navigation remain functional.
- [x] Trades filters, grouped results, target labels, and expandable layers remain functional.
- [x] Light/dark preference persists locally and both themes remain readable.
- [x] Desktop layout passed visual browser review; responsive rules were checked at mobile breakpoints.

## Relevant context

- Affected: `dashboard/templates/base.html`, `index.html`, `trades.html`, and dashboard CSS.
- Preserve uncommitted TP1/TP2/Exit changes already present in `trades.html`.
- No bot, MT5, database, or trading-rule changes are part of this feature.

## Implementation plan and progress

- [x] Inspect both UI systems and current dashboard changes.
- [x] Replace sidebar shell with responsive top navigation and theme toggle.
- [x] Complete reusable dark/light design tokens and page styling.
- [x] Restart only dashboard and verify behavior visually.
- [x] Run relevant checks and finish documentation.

## Verification evidence

Verified on 2026-09-25:

- Flask test client rendered `/` and `/trades` with HTTP 200.
- Browser review confirmed Calendar and Trades in the default dark theme.
- Light theme remained selected after reload and retained readable contrast.
- Expanded a grouped trade and confirmed its execution-layer rows appeared.
- Selected Today and confirmed the URL, date fields, selected preset, and results updated.
- Ran the affected project test suite: 61 passed.
- `python -m pip check` reported no broken requirements.
- `git diff --check` reported no whitespace errors (existing CRLF notices only).
- Dashboard alone was restarted; the existing bot process was not restarted.

Mobile layout is implemented with explicit 860px and 600px breakpoints. The
available browser session did not expose a viewport override, so responsive CSS
was inspected rather than captured at a simulated handset size.

## Operational impact

Dashboard restart required because Flask runs without template auto-reload.
Bot restart is not required.

## Handoff

Complete. The dashboard now follows the LMS reference's glass surfaces, compact
monospace labels, top navigation, theme switcher, entrance motion, and glow
treatment while retaining SignalPilot's gold identity and Flask stack.
