"""Parse GEO M5 entry announcements, excluding result/status messages."""

import math
import re
import unicodedata

from core.signal import Signal


def parse_signal(text: str):
    normalized = unicodedata.normalize("NFKC", text).strip()
    header = re.match(r"GEO\s+(BUY|SELL)\s+TRIGGERED\s*!", normalized, re.I)
    if not header:
        return None
    pair = re.search(r"^\s*Pair\s*:\s*([A-Z]{6})\.?\s*$", normalized, re.I | re.M)
    def price(label):
        match = re.search(r"^\s*" + label + r"\s*:\s*(\d+(?:\.\d+)?)\s*$", normalized, re.I | re.M)
        return float(match.group(1)) if match else None
    entry = price("Entry Price")
    sl = price("Stoploss")
    tps = [price(label) for label in ("1st TP", "2nd TP", "3rd TP")]
    if not pair or any(p is None or not math.isfinite(p) or p <= 0 for p in [entry, sl, *tps]):
        return None
    direction = header.group(1).lower()
    if direction == "buy" and not (sl < entry < tps[0] < tps[1] < tps[2]):
        return None
    if direction == "sell" and not (sl > entry > tps[0] > tps[1] > tps[2]):
        return None
    return Signal(symbol=pair.group(1).upper(), direction=direction,
                  entry_low=entry, entry_high=entry, sl=sl, tps=tps, raw_text=text)