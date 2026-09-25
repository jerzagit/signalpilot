"""
core/autotrade.py
Automatic trading on the MT5 terminal installed on this PC.

Driven by GEO signals:
  * GEO BUY/SELL TRIGGERED  -> open RISK_PERCENT% (by margin) in 0.01-lot
    LAYERS, one separate 0.01 position per layer (hedging account). E.g.
    a 0.08 budget = 8 x 0.01 positions, never one 0.08 blob.
  * Initial stop loss        -> GEO's Stop Loss; order TP -> GEO's last target
    as a safety net (managed messages do the real exits).
  * +BE_PIPS in favour       -> each layer's SL moved to its own fill price
    (breakeven).
  * TP1 HIT (multi-layer)    -> close half of the layers (0.01 each).
  * TP2 / TP3 HIT            -> close the remaining layers.
  * CLOSE ALL / SL HIT       -> close whatever is left.

Only trades opened by this bot (fixed MAGIC) are ever touched. Per-layer
tickets are persisted in data/autotrades.json so a restart does not double-open
or lose track of which layer is which.
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import MetaTrader5 as mt5

from core.config import (
    ACCOUNT_BASELINE,
    AUTO_LOT_SIZE,
    AUTOTRADE_ENABLED,
    BE_PIPS,
    BE_POLL_SECS,
    DB_SYNC_ENABLED,
    MT5_ACCOUNT,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_SYMBOL_MAP,
    MT5_TERMINAL_PATH,
    PIP_SIZE,
    PRICE_TP_CLOSE,
    RISK_PERCENT,
)
from core.db import mark_signal_exit, record_signal, sync_from_mt5
from core.forwarder import notify_admin
from core.signal import FollowUpAlert, Signal

log = logging.getLogger(__name__)

STATE_FILE = Path("data/autotrades.json")
MAGIC = 260924  # identifies trades this bot opened

# trade state: key = "<source_id>:<tag>"
# {
#   key: {
#     "source_id", "tag", "symbol", "mt5_symbol", "direction",
#     "entry" (avg fill), "fills" {ticket(str): entry_price}, "layers",
#     "volume0", "tickets" [int, ...],
#     "sl_geos", "open_ts", "be_done", "tp1_done", "done"
#   }
# }


def _tag_from(raw: str) -> str:
    match = re.search(r"#(\d+)/(\d{8})", raw or "")
    return f"{match.group(1)}/{match.group(2)}" if match else "unknown"


def mt5_symbol(parsed: str) -> str:
    """Map a parsed signal symbol to the broker symbol (XAUUSD -> XAUUSD-VIP)."""
    return MT5_SYMBOL_MAP.get(parsed, parsed)


def _connect() -> bool:
    """Connect to the local MT5 terminal (optionally auto-login the account)."""
    kwargs = {"portable": False}
    if MT5_TERMINAL_PATH:
        kwargs["path"] = MT5_TERMINAL_PATH
    if MT5_LOGIN:
        kwargs["login"] = int(MT5_LOGIN)
    if MT5_PASSWORD:
        kwargs["password"] = MT5_PASSWORD
    if MT5_SERVER:
        kwargs["server"] = MT5_SERVER
    return True if mt5.initialize(**kwargs) else False


def _ready() -> bool:
    """Ensure the MT5 terminal connection is live on the configured account."""
    try:
        if not _connect():
            return False
        info = mt5.terminal_info()
        if not (info and info.connected):
            return False
        account = getattr(mt5.account_info(), "login", 0) or 0
        if MT5_ACCOUNT and str(account) != str(MT5_ACCOUNT):
            log.warning(
                "AUTOTRADE: terminal logged into account %s, expected %s — not trading.",
                account, MT5_ACCOUNT,
            )
            return False
        return True
    except Exception:
        return False


def symbol_pip(symbol: str, digits: int | None = None) -> float:
    """Price units per 1 pip (XAUUSD default 0.10 -> 50 pips = 5.00)."""
    if symbol in PIP_SIZE:
        return PIP_SIZE[symbol]
    if digits is not None:
        return 10 ** -digits
    return 0.10


def _tick(symbol: str) -> tuple[float, float] | None:
    t = mt5.symbol_info_tick(symbol)
    if not t:
        return None
    return (t.bid, t.ask)


def calc_layers(symbol: str, direction: str, equity: float) -> int:
    """n = how many 0.01-lot layers the 5% margin budget can hold (>=1)."""
    price = _tick(symbol)
    if not price:
        return 0
    entry_price = price[1] if direction == "buy" else price[0]
    order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
    margin_01 = mt5.order_calc_margin(order_type, symbol, AUTO_LOT_SIZE, entry_price)
    if margin_01 is None or margin_01 <= 0 or equity <= 0:
        return 0
    budget = (RISK_PERCENT / 100.0) * equity
    n = int(budget // margin_01)
    if n < 1:
        return 0
    step = getattr(mt5.symbol_info(symbol), "volume_step", None) or AUTO_LOT_SIZE
    vol_max = getattr(mt5.symbol_info(symbol), "volume_max", None)
    if vol_max:
        n = min(n, max(int(vol_max // step), 1))
    return n


def _state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _live_positions(symbol: str | None = None) -> list:
    """All live positions opened by this bot's MAGIC (optionally on symbol)."""
    if symbol:
        return [
            p for p in (mt5.positions_get(symbol=symbol) or [])
            if p.magic == MAGIC
        ]
    return [
        p for p in (mt5.positions_get() or [])
        if p.magic == MAGIC
    ]


def _trade_tickets(trade: dict) -> list[int]:
    tickets = trade.get("tickets")
    if isinstance(tickets, list) and tickets:
        return list(tickets)
    if trade.get("ticket"):
        return [int(trade["ticket"])]
    return []


def _trade_fills(trade: dict) -> dict[str, float]:
    fills = trade.get("fills")
    if isinstance(fills, dict) and fills:
        return {str(k): float(v) for k, v in fills.items()}
    fallback = trade.get("entry", 0) or 0
    return {str(t): fallback for t in _trade_tickets(trade)}


def _close_ticket(pos) -> float:
    """Close one live position entirely. Returns volume closed (0 on fail)."""
    tick = _tick(pos.symbol)
    if not tick:
        return 0.0
    side = mt5.ORDER_TYPE_BUY if pos.type == mt5.POSITION_TYPE_SELL else mt5.ORDER_TYPE_SELL
    price = tick[1] if pos.type == mt5.POSITION_TYPE_BUY else tick[0]
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": float(pos.volume),
        "type": side,
        "position": pos.ticket,
        "price": price,
        "magic": MAGIC,
        "comment": "SP TP1",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("AUTOTRADE: close ticket %s failed retcode=%s",
                  pos.ticket, getattr(result, "retcode", "?"))
        return 0.0
    return float(pos.volume)


def _close_all(symbol: str) -> float:
    """Close every MAGIC position on symbol. Returns volume closed."""
    total = 0.0
    for pos in list(_live_positions(symbol)):
        total += _close_ticket(pos)
    return total


def _close_target(symbol: str, n_tickets: int) -> tuple[float, int]:
    """Close up to n_tickets 0.01 positions. Returns (volume, closed count)."""
    closed = 0.0
    count = 0
    for pos in list(_live_positions(symbol)):
        if count >= int(n_tickets):
            break
        got = _close_ticket(pos)
        if got > 0:
            closed += got
            count += 1
    return closed, count


def _sync_db(state: dict) -> None:
    """Mirror the latest MT5 deals into the SQLite calendar store."""
    if not DB_SYNC_ENABLED:
        return
    try:
        ticket_to_tag = {}
        for trade in state.values():
            for t in _trade_tickets(trade):
                ticket_to_tag[int(t)] = trade["tag"]
            if trade.get("ticket"):
                ticket_to_tag[int(trade["ticket"])] = trade["tag"]
        sync_from_mt5(mt5, MAGIC, ticket_to_tag)
    except Exception as exc:
        log.error("AUTOTRADE: db sync failed: %s", exc)


def open_for_signal(signal: Signal, source_id: str, raw: str) -> str:
    """Open the signal as 0.01-lot layers. Returns a human summary."""
    if not AUTOTRADE_ENABLED:
        return ""
    if not _ready():
        log.warning("AUTOTRADE: MT5 terminal not connected — trade skipped.")
        return "AUTO skipped (MT5 not connected)"

    mtsym = mt5_symbol(signal.symbol)
    tag = _tag_from(raw)
    key = f"{source_id}:{tag}"
    state = _state()
    if key in state and state[key].get("done"):
        return "AUTO: duplicate signal ignored"

    if _live_positions(mtsym):
        log.info("AUTOTRADE: position already open on %s — ignoring new signal.", mtsym)
        return "AUTO skipped (position already open)"

    side = "buy" if signal.direction == "buy" else "sell"
    tick = _tick(mtsym)
    if not tick:
        return "AUTO failed (no price tick)"

    info = mt5.account_info()
    if not info:
        return "AUTO failed (no account)"

    layers = calc_layers(mtsym, side, float(info.equity))
    if layers < 1:
        notify_admin(
            f"⚠️ AUTO: margin for 0.01 {mtsym} exceeds {RISK_PERCENT:.0f}% equity "
            f"({info.equity:.2f}) — trade skipped."
        )
        return "AUTO skipped (margin too small)"

    symbol_info = mt5.symbol_info(mtsym)
    if not symbol_info:
        return "AUTO failed (unknown symbol)"

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    sl_price = float(signal.sl)
    tp_price = float(signal.tps[-1]) if signal.tps else 0.0
    base_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": mtsym,
        "volume": AUTO_LOT_SIZE,
        "type": order_type,
        "sl": sl_price,
        "tp": tp_price,
        "magic": MAGIC,
        "comment": f"SP {tag}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    tickets: list[int] = []
    fills: dict[str, float] = {}
    for _ in range(layers):
        request = dict(base_request)
        request["price"] = tick[1] if side == "buy" else tick[0]
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = getattr(result, "retcode", "?")
            log.error("AUTOTRADE: layer order failed retcode=%s %s",
                      code, getattr(result, "comment", ""))
            continue
        fill = float(getattr(result, "price", 0) or request["price"])
        tickets.append(result.order)
        fills[str(result.order)] = fill

    if not tickets:
        notify_admin(f"⚠️ AUTO: no layers filled for {mtsym} — check terminal.")
        return "AUTO failed (no layers filled)"

    entry = round(sum(fills.values()) / len(fills), 2)
    volume0 = round(len(tickets) * AUTO_LOT_SIZE, 2)
    state[key] = {
        "source_id": source_id,
        "tag": tag,
        "symbol": signal.symbol,
        "mt5_symbol": mtsym,
        "direction": side,
        "entry": entry,
        "entry_signal": float(signal.entry_low),
        "fills": fills,
        "layers": len(tickets),
        "volume0": volume0,
        "tickets": tickets,
        "sl_geos": sl_price,
        "tp_safety": tp_price,
        "tps": [float(t) for t in signal.tps],
        "open_ts": int(time.time()),
        "be_done": False,
        "tp1_done": False,
        "done": False,
    }
    _save(state)
    record_signal(
        tag,
        signal.symbol,
        side,
        float(signal.entry_low),
        sl_price,
        [float(t) for t in signal.tps],
        len(tickets),
        received_at=getattr(signal, "received_at", None) or int(time.time()),
    )
    _sync_db(state)
    summary = (
        f"AUTO opened {side.upper()} {signal.symbol} ({mtsym}) "
        f"{len(tickets)}x{AUTO_LOT_SIZE:g} = {volume0:g} lots "
        f"@ {entry:g} SL {sl_price:g} TP {tp_price:g} [tag {tag}]"
    )
    log.info(summary)
    notify_admin(f"✅ {summary}")
    return summary


def handle_followup(followup: FollowUpAlert, source_id: str, raw: str) -> str:
    """React to TP/SL/close-all follow-ups on trades THIS bot opened."""
    if not AUTOTRADE_ENABLED:
        return ""
    if not _ready():
        return "AUTO skipped (MT5 not connected)"

    state = _state()
    tag = _tag_from(raw)
    key = f"{source_id}:{tag}"
    trade = state.get(key)
    if trade is None or trade.get("done"):
        candidates = [
            t for t in state.values()
            if t.get("source_id") == source_id and not t.get("done")
        ]
        if not candidates:
            log.info("AUTOTRADE: no open trade to manage for %s", key)
            return "AUTO: no open trade"
        trade = sorted(candidates, key=lambda t: t.get("open_ts", 0))[-1]
        key = next(k for k, v in state.items() if v is trade)
    return _manage(state, key, trade, followup)


def _manage(state: dict, key: str, trade: dict, followup: FollowUpAlert) -> str:
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    action = followup.action
    level = int(getattr(followup, "level", 0) or 0)
    layers = int(trade.get("layers") or 0)
    volume0 = trade.get("volume0", 0)

    closed_volume = 0.0
    reason = ""
    exit_label = "MAN"

    if action == "tp_hit":
        if level == 1 and layers > 1 and not trade.get("tp1_done"):
            target = max(1, layers // 2)
            closed_volume, closed_layers = _close_target(symbol, target)
            trade["tp1_done"] = True
            reason = f"TP1: closed {closed_volume:g} of {volume0:g} ({closed_layers}/{layers} layers)"
        elif level >= 2:
            closed_volume = _close_all(symbol)
            reason = f"TP{'2' if level == 2 else '3'}: closed {closed_volume:g}"
            exit_label = f"TP{level}"
            trade["done"] = True
        else:
            reason = "TP1: single layer, holding to TP2"
    elif action in ("sl_hit", "close_all", "setup_failed"):
        closed_volume = _close_all(symbol)
        if action == "setup_failed":
            reason = f"setup invalid: closed {closed_volume:g}"
            exit_label = "VOID"
        else:
            reason = f"{action}: closed {closed_volume:g}"
            exit_label = "SL" if action == "sl_hit" else "MAN"
        trade["done"] = True

    if closed_volume:
        log.info("AUTOTRADE [%s]: %s", key, reason)
        notify_admin(f"💰 AUTO {reason} — {symbol} [tag {trade['tag']}]")
    else:
        log.info("AUTOTRADE [%s]: %s", key, reason)
    _save(state)
    _sync_db(state)
    if trade.get("done"):
        mark_signal_exit(trade.get("tag") or key.split(":", 1)[-1], exit_label)
    return reason


def _be_points_for(symbol: str) -> float:
    si = mt5.symbol_info(symbol)
    return BE_PIPS * symbol_pip(symbol, getattr(si, "digits", None))


def _notify_tp_if_reached(trade: dict, tick) -> bool:
    """Notify admin once per TP level when price reaches it. Returns changed."""
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    tps = trade.get("tps") or ([trade["tp_safety"]] if trade.get("tp_safety") else [])
    changed = False
    for index, level in enumerate(tps, start=1):
        flag = f"tp{index}_notified"
        if trade.get(flag):
            continue
        if trade["direction"] == "buy":
            reached = float(tick[0]) >= float(level)
            px = tick[0]
        else:
            reached = float(tick[1]) <= float(level)
            px = tick[1]
        if reached:
            trade[flag] = True
            changed = True
            log.info("AUTOTRADE: TP%d reached %s %s (price %.2f)", index, symbol, trade["direction"], px)
            notify_admin(
                f"🎯 TP{index} reached — {symbol} {trade['direction'].upper()} "
                f"price {px:.2f} vs TP{index} {level:g} [tag {trade['tag']}]"
            )
    return changed


def _close_at_price_targets(trade: dict, tick) -> bool:
    """Close half the layers at TP1 and the rest at TP2+ when live price crosses.

    Mirrors GEO's message-based management so targets are captured in real time
    without waiting for the Telegram follow-up. Flag reuse (tp1_done / done)
    prevents double-closing when both price and message fire for the same level.
    """
    if not PRICE_TP_CLOSE:
        return False
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    tps = trade.get("tps") or ([trade["tp_safety"]] if trade.get("tp_safety") else [])
    if not tps:
        return False
    direction = trade["direction"]
    layers = int(trade.get("layers") or 0)
    changed = False
    for index, level in enumerate(tps, start=1):
        if index == 1:
            if trade.get("tp1_done"):
                continue
        else:
            if trade.get("done"):
                continue
        if direction == "buy":
            reached = float(tick[0]) >= float(level)
        else:
            reached = float(tick[1]) <= float(level)
        if not reached:
            continue
        if index == 1 and layers > 1:
            target = max(1, layers // 2)
            closed_volume, closed_layers = _close_target(symbol, target)
            trade["tp1_done"] = True
            reason = f"TP1: price closed {closed_volume:g} ({closed_layers}/{layers} layers)"
        elif index >= 2:
            closed_volume = _close_all(symbol)
            trade["done"] = True
            trade["exit_price"] = f"TP{index}"
            reason = f"TP{index}: price closed {closed_volume:g}"
        else:
            trade["tp1_done"] = True
            reason = "TP1: single layer, holding to TP2"
        log.info("AUTOTRADE: price-triggered %s — %s", reason, symbol)
        notify_admin(f"💰 AUTO {reason} — {symbol} [tag {trade['tag']}]")
        changed = True
    return changed


def _apply_breakevens(trade: dict, tick, positions: list) -> None:
    """Move each layer's SL to its fill once price is BE_PIPS in favour."""
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    fills = _trade_fills(trade)
    for pos in positions:
        entry = fills.get(str(pos.ticket)) or trade.get("entry") or 0
        if trade["direction"] == "buy":
            hit = (tick[0] - entry) >= _be_points_for(symbol)
        else:
            hit = (entry - tick[1]) >= _be_points_for(symbol)
        if not hit:
            continue
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos.ticket,
            "sl": entry,
            "tp": float(pos.tp) if getattr(pos, "tp", None) else 0.0,
            "magic": MAGIC,
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("AUTOTRADE: breakeven set %s %s layer %s @ %g",
                     symbol, trade["direction"], pos.ticket, entry)
        else:
            log.error("AUTOTRADE: SLTP modify failed retcode=%s",
                      getattr(result, "retcode", "?"))
    trade["be_done"] = True
    notify_admin(
        f"⚖️ AUTO breakeven set — {symbol} {trade['direction'].upper()} "
        f"layers → fill {trade['entry']:g} [tag {trade['tag']}]"
    )


def _monitor_prices() -> None:
    """Poll live trades: TP-arrival notifications, price-triggered TP closes
    (+ breakeven if enabled)."""
    if not AUTOTRADE_ENABLED or not _ready():
        return
    state = _state()
    changed = False
    for key, trade in list(state.items()):
        if trade.get("done"):
            continue
        symbol = trade.get("mt5_symbol") or trade["symbol"]
        positions = _live_positions(symbol)
        if not positions:
            log.info("AUTOTRADE: trade %s closed externally (tag %s)", symbol, trade["tag"])
            trade["done"] = True
            trade["reason"] = "closed (external TP/SL)"
            changed = True
            mark_signal_exit(trade.get("tag") or key.split(":", 1)[-1], "EXT")
            continue
        tick = _tick(symbol)
        if not tick:
            continue
        if _notify_tp_if_reached(trade, tick):
            changed = True
        if _close_at_price_targets(trade, tick):
            changed = True
        if trade.get("done"):
            mark_signal_exit(
                trade.get("tag") or key.split(":", 1)[-1],
                trade.get("exit_price") or "MAN",
            )
            continue
        if BE_PIPS and BE_PIPS > 0 and not trade.get("be_done"):
            _apply_breakevens(trade, _tick(symbol), _live_positions(symbol))
            changed = True
    if changed:
        _save(state)
    _sync_db(state)


async def run_manager_loop() -> None:
    """Background task: poll positions for TP arrivals (+ breakevens)."""
    if not AUTOTRADE_ENABLED:
        return
    while True:
        try:
            await asyncio.to_thread(_monitor_prices)
        except Exception as exc:
            log.error("AUTOTRADE: manager cycle error: %s", exc)
        await asyncio.sleep(BE_POLL_SECS)