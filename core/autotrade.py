"""
core/autotrade.py
Automatic trading on the MT5 terminal installed on this PC.

Driven by GEO signals:
  * GEO BUY/SELL TRIGGERED  -> open RISK_PERCENT% (by margin) in 0.01-lot
    LAYERS, one separate 0.01 position per layer (hedging account). E.g.
    a 0.08 budget = 8 x 0.01 positions, never one 0.08 blob.
  * Initial stop loss        -> GEO's Stop Loss; order TP -> GEO's last target
    as a safety net (managed messages do the real exits).
  * TP1 HIT                  -> close half the layers; the runner's SL moves to
    the TP1 price (TP1-breakeven), so a reverse after TP1 never gives back gain.
  * TP2 HIT (multi-layer)    -> close ~a quarter more; the SL stays at TP1.
  * Exit (TP3 HIT)           -> close whatever is left.
  * CLOSE ALL / SL HIT       -> close whatever is left.

Only trades opened by this bot (fixed MAGIC) are ever touched. Per-layer
tickets are persisted in data/autotrades.json so a restart does not double-open
or lose track of which layer is which.
"""

import asyncio
import json
import logging
import re
import threading
import time
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

import MetaTrader5 as mt5

from core.config import (
    ACCOUNT_BASELINE,
    AUTO_LOT_SIZE,
    AUTOTRADE_ENABLED,
    BE_POLL_SECS,
    DB_SYNC_ENABLED,
    MT5_ACCOUNT,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_SYMBOL_MAP,
    MT5_TERMINAL_PATH,
    PRICE_TP_CLOSE,
    RISK_PERCENT,
)
from core.db import mark_signal_exit, record_signal, sync_from_mt5
from core.forwarder import notify_admin
from core.signal import FollowUpAlert, Signal

log = logging.getLogger(__name__)

STATE_FILE = Path("data/autotrades.json")
MAGIC = 260924  # identifies trades this bot opened
_STATE_LOCK = threading.RLock()
_ADMIN_NOTICES: ContextVar[list[str] | None] = ContextVar(
    "autotrade_admin_notices", default=None
)

# trade state: key = "<source_id>:<tag>"
# {
#   key: {
#     "source_id", "tag", "symbol", "mt5_symbol", "direction",
#     "entry" (avg fill), "fills" {ticket(str): entry_price}, "layers",
#     "volume0", "tickets" [int, ...],
#     "sl_geos", "open_ts", "tp1_closed", "tp1_sl_done", "tp1_done",
#     "tp2_closed", "tp2_done", "pending_action", "done"
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


def _tick(symbol: str) -> tuple[float, float] | None:
    t = mt5.symbol_info_tick(symbol)
    if not t:
        return None
    return (t.bid, t.ask)


def calc_layers(symbol: str, direction: str, equity: float) -> int:
    """Return how many configured lot-size layers fit the margin budget."""
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


def _admin_notice(text: str) -> None:
    notices = _ADMIN_NOTICES.get()
    if notices is None:
        notify_admin(text)
    else:
        notices.append(text)


def _flush_admin_notices(notices: list[str]) -> None:
    for text in notices:
        notify_admin(text)


def _state_locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        notices: list[str] = []
        try:
            with _STATE_LOCK:
                if _ADMIN_NOTICES.get() is not None:
                    return function(*args, **kwargs)
                token = _ADMIN_NOTICES.set([])
                try:
                    result = function(*args, **kwargs)
                finally:
                    notices = _ADMIN_NOTICES.get()
                    _ADMIN_NOTICES.reset(token)
        except BaseException:
            _flush_admin_notices(notices)
            raise
        _flush_admin_notices(notices)
        return result

    return wrapped


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


def _stage_sizes(layers: int) -> tuple[int, int, int]:
    """Multi-layer scale-out: (TP1, TP2, Exit) layer counts from original n.

    TP1 = half, TP2 = about a quarter, Exit = the rest (>= 1 layer). For very
    small layer counts TP2 shrinks to 0 (n=2 -> hold straight to Exit).
    """
    n = int(layers)
    if n <= 0:
        return 0, 0, 0
    if n == 1:
        return 0, 0, 1
    s1 = max(1, n // 2)
    if n - s1 >= 2:
        s2 = min(max(1, round(n / 4)), n - s1 - 1)
    else:
        s2 = 0
    return s1, s2, n - s1 - s2


def _terminal_level(trade: dict, live_layers: int | None = None) -> int:
    try:
        initial_layers = int(
            trade.get("initial_layers") or trade.get("layers") or 0
        )
    except (TypeError, ValueError):
        initial_layers = 0
    if initial_layers < 1:
        if live_layers is None:
            live_layers = len(
                _live_positions(trade.get("mt5_symbol") or trade.get("symbol"))
            )
        initial_layers = live_layers or 2
    return 2 if initial_layers == 1 else 3


def _runner_sl_to_tp1(trade: dict, sl_price: float) -> bool:
    """Anchor the runner's SL at the TP1 price (TP1-breakeven)."""
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    positions = _live_positions(symbol)
    if not positions:
        return False
    success = True
    for pos in positions:
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos.ticket,
            "sl": float(sl_price),
            "tp": float(pos.tp) if getattr(pos, "tp", None) else 0.0,
            "magic": MAGIC,
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("AUTOTRADE: TP1-breakeven set %s layer %s SL -> %g",
                     symbol, pos.ticket, float(sl_price))
        else:
            success = False
            log.error("AUTOTRADE: SLTP modify failed retcode=%s",
                      getattr(result, "retcode", "?"))
    return success


def _release_stage(symbol: str, trade: dict, level: int) -> str:
    """Apply one TP scale-out stage. Shared by message + price paths so both
    behave identically.

    Level 1 (TP1):   close half the layers, then anchor the runner SL at the
                     TP1 price. A single layer only anchors (no close).
    Level 2 (TP2):   close ~a quarter more (multi-layer) and hold; a single
                     layer closes everything at TP2. SL stays at TP1.
    Level >= 3 (Exit): close whatever is left; trade done, recorded as Exit.
    """
    layers = int(trade.get("layers") or 0)
    volume0 = trade.get("volume0", 0)
    tag = trade["tag"]
    tps = trade.get("tps") or ([trade["tp_safety"]] if trade.get("tp_safety") else [])
    tp1 = float(tps[0]) if tps else (float(trade.get("entry") or 0))
    closed = 0.0
    count = 0
    reason = ""

    if trade.get("done"):
        trade.pop("pending_action", None)
        reason = "already closed"
    elif level == 1:
        target = _stage_sizes(layers)[0]
        if "tp1_closed" not in trade:
            trade["tp1_closed"] = target if trade.get("tp1_done") else 0
        previous_count = int(trade.get("tp1_closed") or 0)
        if trade.get("tp1_done") and trade.get("tp1_sl_done"):
            trade.pop("pending_action", None)
            reason = "TP1: already scaled out"
        else:
            remaining = max(0, target - previous_count)
            if remaining:
                closed, count = _close_target(symbol, remaining)
            closed_count = previous_count + count
            trade["tp1_closed"] = closed_count
            if not trade.get("tp1_sl_done"):
                trade["tp1_sl_done"] = _runner_sl_to_tp1(trade, tp1)
            if closed_count >= target and trade.get("tp1_sl_done"):
                trade["tp1_done"] = True
                trade.pop("pending_action", None)
                if layers == 1:
                    reason = "TP1: single layer, holding to TP2"
                elif count and previous_count == 0 and closed_count == target:
                    reason = (
                        f"TP1: closed {closed:g} of {volume0:g} "
                        f"({closed_count}/{layers} layers)"
                    )
                else:
                    reason = (
                        f"TP1: released {closed_count}/{layers} layers; "
                        "SL set at TP1"
                    )
            elif closed_count >= target:
                trade["pending_action"] = "tp1"
                reason = "TP1: SL update pending"
            else:
                trade["pending_action"] = "tp1"
                reason = (
                    f"TP1: closed {closed:g} of {volume0:g} "
                    f"({closed_count}/{layers} layers); close pending"
                )
    elif level == 2:
        if trade.get("tp2_done"):
            trade.pop("pending_action", None)
            reason = "TP2: already scaled out"
        elif layers > 1:
            target = _stage_sizes(layers)[1]
            previous_count = int(trade.get("tp2_closed") or 0)
            remaining = max(0, target - previous_count)
            if remaining:
                closed, count = _close_target(symbol, remaining)
            closed_count = previous_count + count
            trade["tp2_closed"] = closed_count
            if closed_count >= target:
                trade["tp2_done"] = True
                trade.pop("pending_action", None)
                if target == 0:
                    reason = "TP2: holding to Exit"
                elif count and previous_count == 0 and closed_count == target:
                    reason = f"TP2: closed {closed:g} ({closed_count}/{layers} layers)"
                else:
                    reason = f"TP2: released {closed_count}/{layers} layers"
            else:
                trade["pending_action"] = "tp2"
                reason = (
                    f"TP2: closed {closed:g} ({closed_count}/{layers} layers); "
                    "close pending"
                )
        else:
            closed = _close_all(symbol)
            if _live_positions(symbol):
                trade["pending_action"] = "tp2"
                reason = f"TP2: closed {closed:g}; close pending"
            else:
                reason = f"TP2: closed {closed:g}"
                trade["tp2_done"] = True
                trade["done"] = True
                trade["exit_price"] = "TP2"
                trade.pop("pending_action", None)
    elif level >= 3:
        closed = _close_all(symbol)
        if _live_positions(symbol):
            trade["pending_action"] = "exit"
            reason = f"Exit: closed {closed:g}; close pending"
        else:
            reason = f"Exit: closed {closed:g}"
            trade["done"] = True
            trade["exit_price"] = "Exit"
            trade.pop("pending_action", None)
    else:
        reason = f"unrecognized TP level: {level}"

    if closed:
        log.info("AUTOTRADE: %s — %s [tag %s]", reason, symbol, tag)
        _admin_notice(f"💰 AUTO {reason} — {symbol} [tag {tag}]")
    else:
        log.info("AUTOTRADE: %s — %s [tag %s]", reason, symbol, tag)
    return reason


def _retry_pending_action(symbol: str, trade: dict) -> bool:
    action = trade.get("pending_action")
    if not action:
        return False
    if action == "tp1":
        _release_stage(symbol, trade, 1)
    elif action == "tp2":
        _release_stage(symbol, trade, 2)
    elif action == "exit":
        _release_stage(symbol, trade, 3)
    elif action in ("sl_hit", "close_all", "setup_failed"):
        closed = _close_all(symbol)
        if _live_positions(symbol):
            reason = f"{action}: closed {closed:g}; close pending"
        else:
            reason = f"{action}: closed {closed:g}"
            trade["done"] = True
            trade["exit_price"] = {
                "sl_hit": "SL",
                "close_all": "MAN",
                "setup_failed": "VOID",
            }[action]
            trade.pop("pending_action", None)
        log.info("AUTOTRADE: %s — %s [tag %s]", reason, symbol, trade["tag"])
        if closed:
            _admin_notice(f"💰 AUTO {reason} — {symbol} [tag {trade['tag']}]")
    else:
        log.error("AUTOTRADE: unknown pending action %s", action)
        trade.pop("pending_action", None)
    return True


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


@_state_locked
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
        _admin_notice(
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
        _admin_notice(f"⚠️ AUTO: no layers filled for {mtsym} — check terminal.")
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
        "tp1_closed": 0,
        "tp1_sl_done": False,
        "tp1_done": False,
        "tp2_closed": 0,
        "tp2_done": False,
        "pending_action": None,
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
    _admin_notice(f"✅ {summary}")
    return summary


@_state_locked
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


@_state_locked
def _manage(state: dict, key: str, trade: dict, followup: FollowUpAlert) -> str:
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    action = followup.action
    level = int(getattr(followup, "level", 0) or 0)

    reason = ""
    exit_label = "MAN"

    if action == "tp_hit":
        if trade.get("done"):
            reason = "AUTO: trade already closed"
        elif trade.get("pending_action") and level < _terminal_level(trade):
            reason = f"AUTO: waiting for {trade['pending_action']}"
        else:
            reason = _release_stage(symbol, trade, level)
        if trade.get("done"):
            exit_label = trade.get("exit_price") or "MAN"
    elif action in ("sl_hit", "close_all", "setup_failed"):
        if trade.get("done"):
            reason = "AUTO: trade already closed"
        else:
            closed_volume = _close_all(symbol)
            if action == "setup_failed":
                reason = f"setup invalid: closed {closed_volume:g}"
                exit_label = "VOID"
            else:
                reason = f"{action}: closed {closed_volume:g}"
                exit_label = "SL" if action == "sl_hit" else "MAN"
            if _live_positions(symbol):
                trade["pending_action"] = action
                reason += "; close pending"
            else:
                trade["done"] = True
                trade["exit_price"] = exit_label
                trade.pop("pending_action", None)
            if closed_volume:
                log.info("AUTOTRADE [%s]: %s", key, reason)
                _admin_notice(f"💰 AUTO {reason} — {symbol} [tag {trade['tag']}]")
            else:
                log.info("AUTOTRADE [%s]: %s", key, reason)
    else:
        reason = f"unhandled followup: {action}"

    _save(state)
    _sync_db(state)
    if trade.get("done"):
        mark_signal_exit(
            trade.get("tag") or key.split(":", 1)[-1],
            trade.get("exit_price") or exit_label,
        )
    return reason


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
            label = "Exit" if index == 3 else f"TP{index}"
            log.info("AUTOTRADE: %s reached %s %s (price %.2f)", label, symbol, trade["direction"], px)
            _admin_notice(
                f"🎯 {label} reached — {symbol} {trade['direction'].upper()} "
                f"price {px:.2f} vs {label} {level:g} [tag {trade['tag']}]"
            )
    return changed


def _close_at_price_targets(trade: dict, tick) -> bool:
    """Stage the scale-out as live price crosses each target, mirroring the
    message-driven path (_manage -> _release_stage) so targets are captured in
    real time. Flags (tp1_done / tp2_done / done) prevent double-processing
    when price and message both fire for the same level."""
    if not PRICE_TP_CLOSE or trade.get("done"):
        return False
    symbol = trade.get("mt5_symbol") or trade["symbol"]
    tps = trade.get("tps") or ([trade["tp_safety"]] if trade.get("tp_safety") else [])
    if not tps:
        return False
    direction = trade["direction"]
    pending = trade.get("pending_action")
    if pending:
        terminal_level = _terminal_level(trade)
        if pending in ("tp1", "tp2") and len(tps) >= terminal_level:
            terminal_price = float(tps[terminal_level - 1])
            if direction == "buy":
                terminal_reached = float(tick[0]) >= terminal_price
            else:
                terminal_reached = float(tick[1]) <= terminal_price
            if terminal_reached:
                _release_stage(symbol, trade, terminal_level)
                return True
        return False
    changed = False
    for index, level in enumerate(tps, start=1):
        if index == 1 and trade.get("tp1_done") and trade.get("tp1_sl_done"):
            continue
        if index == 2 and trade.get("tp2_done"):
            continue
        if trade.get("done"):
            break
        if direction == "buy":
            reached = float(tick[0]) >= float(level)
        else:
            reached = float(tick[1]) <= float(level)
        if not reached:
            continue
        _release_stage(symbol, trade, index)
        changed = True
        if index == 1 and not trade.get("tp1_done"):
            break
        if index == 2 and not trade.get("tp2_done"):
            break
    return changed


@_state_locked
def _monitor_prices() -> None:
    """Poll live trades: TP-arrival notifications and price-triggered TP closes
    (TP1-breakeven is applied inside the scale-out stages)."""
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
        tp1_retry = (
            trade.get("tp1_done") and not trade.get("tp1_sl_done")
        ) or (
            int(trade.get("tp1_closed") or 0) > 0
            and not trade.get("tp1_done")
        )
        tp2_retry = (
            int(trade.get("tp2_closed") or 0) > 0
            and not trade.get("tp2_done")
        )
        retry_needed = bool(trade.get("pending_action")) or tp1_retry or tp2_retry
        if retry_needed:
            if trade.get("pending_action"):
                _retry_pending_action(symbol, trade)
            elif tp1_retry:
                _release_stage(symbol, trade, 1)
            else:
                _release_stage(symbol, trade, 2)
            changed = True
        if trade.get("done"):
            mark_signal_exit(
                trade.get("tag") or key.split(":", 1)[-1],
                trade.get("exit_price") or "MAN",
            )
            continue
        tick = _tick(symbol)
        if not tick:
            continue
        if not trade.get("pending_action") and _notify_tp_if_reached(trade, tick):
            changed = True
        if _close_at_price_targets(trade, tick):
            changed = True
        if trade.get("done"):
            mark_signal_exit(
                trade.get("tag") or key.split(":", 1)[-1],
                trade.get("exit_price") or "MAN",
            )
            continue
    if changed:
        _save(state)
    _sync_db(state)


async def run_manager_loop() -> None:
    """Background task: poll positions for TP arrivals and scale-out stages."""
    if not AUTOTRADE_ENABLED:
        return
    while True:
        try:
            await asyncio.to_thread(_monitor_prices)
        except Exception as exc:
            log.error("AUTOTRADE: manager cycle error: %s", exc)
        await asyncio.sleep(BE_POLL_SECS)