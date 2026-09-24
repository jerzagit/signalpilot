# SignalPilotV1 — Auto-Trade System (MT5)

## Overview

The bot reacts to GEO V5 VIP signals posted to the watched Telegram source and
trades them automatically on the **MT5 terminal installed on this PC**. It only
ever touches orders it opened itself (fixed magic `260924`).

Drivers:

| Trigger | Action |
| --- | --- |
| `GEO BUY TRIGGERED!` / `GEO SELL TRIGGERED!` | Open market order |
| `TP1 HIT` | Close half of the layers (multi-layer only) |
| `TP2 HIT` | Close the rest (single layer: everything) |
| `TP3 HIT` | Close whatever is left |
| `CLOSE ALL POSITION NOW` | Close whatever is left |
| `SL HIT` | Close whatever is left (ensure exit) |

## Money Management

- **Risk budget**: `RISK_PERCENT` (5%) of current **account equity**.
- **Lot size**: totals `0.01 x n` lots, where `n` = number of `AUTO_LOT_SIZE`
  (0.01) layers that fit inside the 5% margin budget:
  `n = floor(5% x equity / margin_for_0.01_lot)`.
- **Pip size** (gold): `AUTO_PIP_SIZE=XAUUSD=0.10` → **50 pips = 5.00** price
  distance.
- **Breakeven**: when price moves `BE_PIPS` (50 = 5.00) in favor, the stop loss
  is moved to the entry price. Applies to single- and multi-layer alike.

### Exit behaviour by layer count

| Layers (`n`) | TP1 HIT | TP2 / TP3 HIT |
| --- | --- | --- |
| 1 (0.01 x 1) | Hold (`BREAKEVEN` already handled) | Close all at TP2 |
| >1 (0.01 x n) | Close `n // 2` layers (at least 1) | Close the rest |

Example: 5 layers opened → `TP1 HIT` closes 2 layers (0.02), `TP2 HIT` closes
the remaining 3 (0.03).

## Order Details

- **Entry**: current market price at trigger time.
- **Initial SL**: GEO's *Stoploss* value.
- **Order TP**: GEO's last target — a safety net only; real exits are driven by
  the follow-up messages above.
- **Magic**: `260924` (identifies bot trades; human trades are never touched).
- **Dedupe**: one trade per `Signal Tag` per source; duplicates ignored. State is
  persisted in `data/autotrades.json` so a bot restart does not double-open.

## Operational Notes

- Requires the **MT5 terminal to be running and logged in** with the
  **Algo trading** button enabled; Python connects through the installed
  `MetaTrader5` package (installed in `.venv`).
- A background monitor polls live positions every `BE_POLL_SECS` (5s) and
  applies the breakeven move; it also marks trades "closed" if they exited
  externally (e.g. terminal SL/TP).
- Every open / breakeven / close sends a notification to the bot admins
  (`ADMIN_CHATS`).

## Enabling

In `.env`:

```
AUTOTRADE_ENABLED=true    # flip to true to go live
RISK_PERCENT=5
AUTO_LOT_SIZE=0.01
AUTO_PIP_SIZE=XAUUSD-VIP=0.10
BE_PIPS=50
BE_POLL_SECS=5
MT5_TERMINAL_PATH=        # optional explicit path, auto-detected if blank
MT5_ACCOUNT=1288795       # guard: only trades when THIS login is active
MT5_LOGIN=1288795         # auto-login credentials (optional)
MT5_PASSWORD=<on-demo-account>
MT5_SERVER=VTMarkets-Demo
MT5_SYMBOL_MAP=XAUUSD=XAUUSD-VIP
```

Then restart the bot (`python bot.py`). The bot connects to the local MT5
terminal (auto-logging into the configured login if the terminal is not
already there), and refuses to trade unless `MT5_ACCOUNT` is the active login.

## Current Account (demo)

| Setting | Value |
| --- | --- |
| Account | 1288795 |
| Type | Standard STP |
| Leverage | 500 : 1 |
| Server | VTMarkets-Demo |
| Balance | ≈ 1417.74 USD |

With a gold margin of ~$8.50 per 0.01 layer at 500:1 leverage (~$4,250 price),
the 5% budget (~$70.9) works out to roughly **8 layers ≈ 0.08 lots** per signal.

Keep the MT5 terminal running and logged into account `1288795` with the
**Algo trading** button enabled while the bot is live.