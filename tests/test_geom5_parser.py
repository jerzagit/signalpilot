import pytest

from core.parsers import parse_with_profile


SELL = """GEO SELL TRIGGERED!
Signal Tag: #006/20260922
Pair: XAUUSD.
TimeFrame: M5
Stoploss : 4322.27
Entry Price : 4310.26
1st TP : 4305.26
2nd TP : 4300.26
3rd TP : 4295.26"""

BUY = """GEO BUY TRIGGERED!
Pair: XAUUSD.
Stoploss : 4320.10
Entry Price : 4331.74
1st TP : 4336.74
2nd TP : 4341.74
3rd TP : 4346.74"""


@pytest.mark.parametrize("raw,direction,entry,sl,tps", [
    (SELL, "sell", 4310.26, 4322.27, [4305.26, 4300.26, 4295.26]),
    (BUY, "buy", 4331.74, 4320.10, [4336.74, 4341.74, 4346.74]),
])
def test_entries(raw, direction, entry, sl, tps):
    signal = parse_with_profile("geom5", raw)
    assert (signal.symbol, signal.direction, signal.entry_low, signal.entry_high, signal.sl, signal.tps) == (
        "XAUUSD", direction, entry, entry, sl, tps
    )


@pytest.mark.parametrize("raw", [
    BUY.replace("Stoploss : 4320.10", ""),
    BUY.replace("4320.10", "4350.00"),
    BUY.replace("3rd TP : 4346.74", ""),
])
def test_invalid_entries_rejected(raw):
    assert parse_with_profile("geom5", raw) is None