# Multi-layer scale-out + TP1-breakeven

Status: complete
Updated: 2026-09-25

## Goal and scope

Multi-layer trades were fully closed at TP2, so the Exit (TP3) level never
existed in the exit logic. Also, breakeven was entry-based (BE_PIPS=50 -> SL to
entry). Change to a 3-stage scale-out with a **TP1-breakeven** and remove the
entry breakeven.

## Acceptance criteria

- [x] Multi-layer: TP1 closes half and anchors the runner SL at the TP1 price.
- [x] Multi-layer: TP2 closes ~a quarter more; runner SL stays at TP1.
- [x] Multi-layer: Exit (level 3) closes the rest; trade recorded as Exit.
- [x] Single layer: no close at TP1, but SL anchored at TP1; closes all at TP2.
- [x] Entry breakeven (BE_PIPS) removed; `BE_PIPS` no longer read.

## Relevant context

- Affected module: `core/autotrade.py`; docs: AUTOTRADE.md.
- Both the Telegram-message path (`_manage`) and the price-cross path
  (`_close_at_price_targets`) now share one `_release_stage()` so they cannot
  drift apart; `tp1_done` / `tp2_done` / `done` flags prevent double-processing
  when both paths fire for the same level.
- Decisions: replace entry-BE with TP1-BE; runner SL stays at TP1 (no step to
  TP2); single layer protected at TP1 as well; stage sizes half / ~quarter /
  rest with min 1 layer where possible (n=2 -> TP2 is a hold to Exit).
- `.env` key `BE_PIPS` is now unused by the code but left in place.

## Implementation

- `_stage_sizes(n)` -> `(s1, s2, s3)`: TP1 half, TP2 `min(max(1, round(n/4)),
  n - s1 - 1)` or 0, Exit the rest.
- `_runner_sl_to_tp1()` anchors live runner SL at `tps[0]` (SLTP modify).
- `_release_stage(symbol, trade, level)` performs each stage and is shared by
  `_manage` and `_close_at_price_targets`.
- Removed `_be_points_for` / `_apply_breakevens` and the entry-BE block in
  `_monitor_prices`; removed `BE_PIPS` import; added state flag `tp2_done`.
- Level-3 admin notify now reads "Exit reached".

## Verification evidence

- `.venv\Scripts\python.exe -m pytest tests/test_autotrade.py tests/test_forwarder.py
  tests/test_db_levels.py tests/test_card_image.py tests/test_followup_parser.py
  tests/test_geom5_parser.py -q` -> 61 passed.
- `.venv\Scripts\python.exe -m py_compile core/autotrade.py`.
- `.venv\Scripts\python.exe -m pip check`; `git diff --check`.
- Test-only: MT5, Telegram, and DB writes are mocked/stubbed (hermetic).

## Operational impact

Restart the bot so the updated module is loaded. Existing persisted state in
`data/autotrades.json` is backward compatible (old `be_done` key is simply
ignored). No schema changes.

## Handoff

Complete. Known trade-off (user-confirmed): there is no protection before TP1 —
a reversal below TP1 takes the full position risk until the TP1 level is hit.