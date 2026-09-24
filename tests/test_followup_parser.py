from core.signal import attach_source_context, parse_followup_alert
from core.parsers import parse_with_profile


def test_tp_hit_levels():
    alert = parse_followup_alert("TP1 HIT")
    assert alert is not None
    assert alert.action == "tp_hit"
    assert alert.level == 1


def test_all_tp_hit_levels():
    for level in ("1", "2", "3"):
        alert = parse_followup_alert(f"TP{level} HIT")
        assert alert.action == "tp_hit"
        assert alert.level == int(level)


def test_sl_hit():
    alert = parse_followup_alert("SL HIT XAUUSD")
    assert alert is not None
    assert alert.action == "sl_hit"
    assert alert.symbol == "XAUUSD"


def test_close_all():
    alert = parse_followup_alert("CLOSE ALL POSITION NOW")
    assert alert is not None
    assert alert.action == "close_all"


def test_result_messages_never_become_entries():
    for header in ("SL HIT", "TP1 HIT", "TP2 HIT", "TP3 HIT", "CLOSE ALL POSITION NOW"):
        raw = ("GEO BUY TRIGGERED!\n"
               "Pair: XAUUSD.\n"
               "Stoploss : 4320.10\n"
               "Entry Price : 4331.74\n"
               "1st TP : 4336.74\n"
               "2nd TP : 4341.74\n"
               "3rd TP : 4346.74").replace("GEO BUY TRIGGERED!", header)
        assert parse_with_profile("geom5", raw) is None


def test_attach_source_context_fills_missing_symbol():
    alert = parse_followup_alert("TP1 HIT")
    assert alert.symbol is None
    attach_source_context(alert, symbol="XAUUSD", direction="sell")
    assert alert.symbol == "XAUUSD"
    assert alert.direction == "sell"


def test_attach_source_context_keeps_explicit_symbol():
    alert = parse_followup_alert("SL HIT XAUUSD")
    assert alert.symbol == "XAUUSD"
    attach_source_context(alert, symbol="EURUSD", direction="buy")
    assert alert.symbol == "XAUUSD"