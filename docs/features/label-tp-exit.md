# Target label fix: TP1 / TP2 / Exit

Status: complete
Updated: 2026-09-25

## Goal and scope

Forwarded signal cards labelled the three GEO targets as "Profit / TP1 / TP2",
which did not match the follow-up levels (TP1 HIT / TP2 HIT / TP3 HIT) or the
dashboard badges. Rename everywhere the target appears so the final level reads
"Exit" instead of "Profit"/"TP3".

## Acceptance criteria

- [x] Signal card (text) labels targets TP1, TP2, Exit; "Profit" no longer appears.
- [x] Card image (PNG) boxes label targets TP1, TP2, EXIT.
- [x] Follow-up card for level 3 reads "Exit hit" (not "TP3 hit"); TP1/TP2 unchanged.
- [x] Dashboard close levels/badges/targets read TP1, TP2, Exit.

## Relevant context

- Affected modules: `core/forwarder.py`, `core/card_image.py`, `core/db.py`,
  `dashboard/templates/trades.html`, `tests/test_forwarder.py`.
- GEO signals carry exactly three targets (1st/2nd/3rd TP). The last is the exit.
- Functional levels in autotrade/follow-up parsing are unchanged (GEO still
  sends "TP3 HIT" as the closing event); only display labels were renamed.
- Pre-existing: two identical `close_level` definitions in `core/db.py` (see
  docs/ARCHITECTURE.md). Only the live second definition was updated here.

## Implementation

- `core/forwarder.py`: `_TP_LABELS = ("TP1", "TP2", "Exit")`; new `_level_label()`
  helper; level-3 follow-up renders "Exit hit".
- `core/card_image.py`: boxes labelled ("TP1", "TP2", "EXIT").
- `core/db.py`: `close_level` maps the final target index to "Exit"; new
  `_level_rank` ordering used for badge sort and group exit label.
- `dashboard/templates/trades.html`: target cells and badges render TP1/TP2/Exit;
  "Exit" badge uses the exit tone.
- `tests/test_forwarder.py`, new `tests/test_db_levels.py`.

## Verification evidence

- `.venv\Scripts\python.exe -m pytest tests/test_geom5_parser.py tests/test_followup_parser.py
  tests/test_forwarder.py tests/test_card_image.py tests/test_db_levels.py tests/test_autotrade.py -q`
  -> 61 passed.
- `.venv\Scripts\python.exe -m pip check`
- `git diff --check`

## Operational impact

Restart the service(s) that render cards/follow-ups (listener forward path) when
deploying; no schema or data migration needed. Dashboard-only change is picked
up on reload. No trading settings touched.

## Handoff

Complete. Cards and dashboard now agree on TP1 / TP2 / Exit. Note: the duplicate
`close_level` in core/db.py remains a known cleanup item flagged in
docs/ARCHITECTURE.md.