# SignalPilotV1 — Auto-Trade System (MT5)

## Overview

The bot reacts to GEO V5 VIP signals posted to the watched Telegram source and
trades them automatically on the **MT5 terminal installed on this PC**. It only
ever touches orders it opened itself (fixed magic `260924`).

Drivers:

| Trigger | Action |
| --- | --- |
| `GEO BUY TRIGGERED!` / `GEO SELL TRIGGERED!` | Open market order |
| `TP1 HIT` | Close half the layers; the runner's SL moves to the **TP1 price** (TP1-breakeven) |
| `TP2 HIT` | Multi-layer: close ~a quarter more (SL stays at TP1); single layer: close everything |
| `Exit` / `TP3 HIT` | Close whatever is left |
| `CLOSE ALL POSITION NOW` | Close whatever is left |
| `SL HIT` | Close whatever is left (ensure exit) |

## Money Management

- **Risk budget**: `RISK_PERCENT` of current **account equity**.
- **Lot size**: totals `AUTO_LOT_SIZE x n`, where `n` is the number of layers
  that fit inside the configured margin budget:
  `n = floor((RISK_PERCENT / 100) x equity / margin_for_AUTO_LOT_SIZE)`.
- **TP1-breakeven**: protection starts when price reaches TP1 — the runner's
  stop loss is moved to the **TP1 price**, so a reversal after TP1 still exits
  at TP1 (profit locked). Applies to single- and multi-layer alike.

### Exit behaviour by layer count

| Layers (`n`) | TP1 HIT | TP2 HIT | Exit / TP3 HIT |
| --- | --- | --- | --- |
| 1 | Hold; SL → TP1 | Close the only layer | — |
| 2 | Close 1; SL → TP1 | Hold | Close the last layer |
| 3 or more | Close `n // 2`; SL → TP1 | Close about `n / 4`, always leaving at least 1 for Exit | Close the rest |

Example: 8 layers opened → `TP1 HIT` closes 4 (0.04) and locks the runner SL at
TP1; `TP2 HIT` closes 2 more (0.02); `Exit` closes the last 2 (0.02). A 2-layer
trade skips TP2 (1 at TP1, 1 at Exit).

## Order Details

- **Entry**: current market price at trigger time.
- **Initial SL**: GEO's *Stoploss* value.
- **Order TP**: GEO's last target — a safety net only. Telegram follow-ups and,
  when `PRICE_TP_CLOSE=true`, live target crossings use the same serialized,
  resumable scale-out path. Completed-stage flags and counts prevent normal
  trigger overlap; incomplete broker operations remain pending for retry. A
  final Exit signal or target supersedes a pending TP1/TP2 operation.
- **Magic**: `260924` (identifies bot trades; human trades are never touched).
- **Dedupe**: one trade per `Signal Tag` per source; duplicates ignored. State is
  persisted in `data/autotrades.json` so a bot restart does not double-open.

## Operational Notes

- Requires the **MT5 terminal to be running and logged in** with the
  **Algo trading** button enabled; Python connects through the installed
  `MetaTrader5` package (installed in `.venv`).
- A background monitor polls live positions every `BE_POLL_SECS` (default 5s).
  When `PRICE_TP_CLOSE=true`, it applies target scale-outs and marks trades
  closed if they exited externally (for example, through terminal SL/TP).
- Open, target-reached, scale-out, and close events notify the configured bot
  admins (`ADMIN_CHATS`).
- State updates from message handling, price monitoring, and trade opening are
  serialized; admin notifications are sent after that lock is released.
  Incomplete closes or SL updates remain pending and retry each monitor cycle.
  Legacy `tp1_done` state is upgraded by anchoring TP1 without closing those
  layers again. A hard process interruption after broker accepts an order but
  before state is saved can still require manual reconciliation.

## Enabling

In `.env`:

```
AUTOTRADE_ENABLED=true    # flip to true to go live
RISK_PERCENT=5
AUTO_LOT_SIZE=0.01
PRICE_TP_CLOSE=true
BE_POLL_SECS=5
MT5_TERMINAL_PATH=        # optional explicit path, auto-detected if blank
MT5_ACCOUNT=<account-login>
MT5_LOGIN=                 # optional; leave blank when the terminal is logged in
MT5_PASSWORD=
MT5_SERVER=
MT5_SYMBOL_MAP=XAUUSD=XAUUSD-VIP
```

Then restart the bot (`python bot.py`). The bot connects to the local MT5
terminal and can auto-login when credentials are configured. When
`MT5_ACCOUNT` is set, it refuses to trade unless that account is active.

Keep the MT5 terminal running and logged into the configured account with the
**Algo trading** button enabled while the bot is live.