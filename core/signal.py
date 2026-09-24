"""
core/signal.py
Signal data model and follow-up alert detection shared by parsers.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Signal:
    symbol: str
    direction: str          # "buy" | "sell"
    entry_low: float
    entry_high: float
    sl: float
    tps: list               # [tp1, tp2, ...]
    raw_text: str
    created_at: float = field(default_factory=time.time)
    source_id: str = ""
    source_name: str = ""
    parser_profile: str = ""

    @property
    def entry_mid(self) -> float:
        return round((self.entry_low + self.entry_high) / 2, 5)

    @property
    def is_range_entry(self) -> bool:
        return self.entry_low != self.entry_high


@dataclass
class FollowUpAlert:
    symbol: Optional[str]   # None means "all open positions"
    direction: Optional[str]  # "buy" | "sell" | None
    action: str             # tp_hit | sl_hit | close_all | setup_failed | early_tp |
                            # collect_profit | close_half | breakeven
    raw_text: str
    confidence: float = 1.0
    reasoning: str = ""
    level: int = 0          # for tp_hit: which target was reached (1/2/3…)


def attach_source_context(
    alert: FollowUpAlert,
    symbol: Optional[str],
    direction: Optional[str],
) -> FollowUpAlert:
    """Fill missing symbol/direction from the last signal seen on the same source."""
    if alert.symbol is None and symbol:
        alert.symbol = symbol
    if alert.direction is None and direction:
        alert.direction = direction
    return alert


def parse_followup_alert(text: str) -> Optional[FollowUpAlert]:
    """
    Detect channel follow-up instructions after a trade signal is running
    (TP/SL hit, close all, collect profit, breakeven, close half). These are
    forwarded to subscribers so they can manage their open positions.
    """
    lower = text.strip().lower()
    if not lower:
        return None

    symbol = _extract_symbol(lower)
    direction = _extract_direction(lower)

    if "setup failed" in lower:
        return FollowUpAlert(symbol, direction, "setup_failed", text)

    if re.search(r"\bclose\s+all\b", lower):
        return FollowUpAlert(symbol, direction, "close_all", text)

    sl_hit = re.search(r"\bsl\s*hit\b", lower)
    if sl_hit:
        return FollowUpAlert(symbol, direction, "sl_hit", text)

    tp_hit = re.search(r"\btp\s*(\d*)\s*hits?\b", lower)
    if tp_hit:
        level = int(tp_hit.group(1)) if tp_hit.group(1) else 0
        return FollowUpAlert(symbol, direction, "tp_hit", text, level=level)

    if any(trigger in lower for trigger in (
        "breakeven", "break even", "break-even", "set be", "secure be",
        "sl to entry", "sl entry", "risk free", "free risk",
    )):
        return FollowUpAlert(symbol, direction, "breakeven", text)

    if any(trigger in lower for trigger in (
        "close half", "close 1/2", "close 50", "close 50%",
        "half close", "partial close", "secure half",
    )):
        return FollowUpAlert(symbol, direction, "close_half", text)

    if any(trigger in lower for trigger in (
        "collect profit", "mau collect", "siapa mau collect", "collect and",
    )):
        return FollowUpAlert(symbol, direction, "collect_profit", text)

    if any(trigger in lower for trigger in (
        "siapa nak collect", "collect dulu", "dipersilakan", "dipersialakan",
        "take profit now", "early tp", "secure profit", "running profit",
        "profit running",
    )):
        return FollowUpAlert(symbol, direction, "early_tp", text)

    if re.search(r"\bprofit\s+\d+\s*pips?\b", lower):
        return FollowUpAlert(symbol, direction, "early_tp", text)

    return None


def _extract_direction(lower: str) -> Optional[str]:
    if re.search(r"\b(buy|long)\b", lower):
        return "buy"
    if re.search(r"\b(sell|short)\b", lower):
        return "sell"
    return None


def _extract_symbol(lower: str) -> Optional[str]:
    if re.search(r"\b(gold|xau)\b", lower):
        return "XAUUSD"
    m = re.search(r"\b(xauusd|eurusd|gbpusd|usdjpy|[a-z]{3}usd|usd[a-z]{3})\b", lower)
    return m.group(1).upper() if m else None