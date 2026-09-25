from core.forwarder import build_followup_card, build_signal_card
from core.signal import FollowUpAlert, Signal


def _signal() -> Signal:
    return Signal(
        symbol="XAUUSD",
        direction="buy",
        entry_low=4310.26,
        entry_high=4310.26,
        sl=4320.10,
        tps=[4336.74, 4341.74, 4346.74],
        raw_text="raw",
    )


def test_signal_card_contains_key_fields():
    card = build_signal_card(_signal(), "Geom V5")
    assert "XAUUSD" in card
    assert "BUY" in card
    assert "4310.26" in card
    assert "4320.10" in card
    assert "4336.74" in card


def test_signal_card_uses_requested_labels():
    card = build_signal_card(_signal(), "Geom V5")
    assert "Entry         :" in card
    assert "Stop Loss (SL):" in card
    assert "TP1" in card
    assert "TP2" in card
    assert "Exit" in card
    assert "Profit" not in card
    assert "Pm admin for auto-trade" in card


def test_signal_card_hides_source_by_default():
    card = build_signal_card(_signal(), "Geom V5")
    assert "Geom V5" not in card


def test_signal_card_can_show_source():
    card = build_signal_card(_signal(), "Geom V5", show_source=True)
    assert "Geom V5" in card


def test_signal_card_does_not_echo_original_wording():
    card = build_signal_card(_signal(), "Geom V5")
    for original_term in ("GEO", "TRIGGERED", "Stoploss", "Entry Price", "1st TP", "TimeFrame"):
        assert original_term not in card


def test_signal_card_balanced_backticks():
    card = build_signal_card(_signal(), "Geom V5")
    assert card.count("`") % 2 == 0


def test_signal_card_with_news_context():
    card = build_signal_card(_signal(), "Geom V5", news_context=[
        "Gold slips on Fed tightening bets",
        "Dollar holds steady ahead of FOMC",
    ])
    assert "Gold slips on Fed tightening bets" in card
    assert "Dollar holds steady ahead of FOMC" in card
    assert "Not financial advice" in card


def test_signal_card_without_news_has_no_news_rows():
    card = build_signal_card(_signal(), "Geom V5")
    assert "📰" not in card


def test_range_entry_formatting():
    signal = _signal()
    signal.entry_low = 4310.26
    signal.entry_high = 4315.00
    card = build_signal_card(signal, "")
    assert "4310.26" in card
    assert "4315.00" in card


def test_signal_card_has_timestamp():
    import re

    card = build_signal_card(_signal(), "Geom V5")
    assert "⏱" in card
    assert re.search(r"\d{1,2} \w{3} \d{1,2}:\d{2}(am|pm)", card)


def test_followup_card_label():
    alert = FollowUpAlert(symbol="XAUUSD", direction="sell", action="early_tp", raw_text="TAKE PROFIT NOW")
    card = build_followup_card(alert, "Geom V5", "TAKE PROFIT NOW")
    assert "Collect targets" in card
    assert "XAUUSD" in card


def test_tp_hit_card_shows_level():
    alert = FollowUpAlert(symbol="XAUUSD", direction="buy", action="tp_hit", raw_text="TP2 HIT", level=2)
    card = build_followup_card(alert, raw_text="TP2 HIT")
    assert "TP2 hit" in card
    assert "XAUUSD" in card


def test_sl_hit_card():
    alert = FollowUpAlert(symbol="XAUUSD", direction="sell", action="sl_hit", raw_text="SL HIT")
    card = build_followup_card(alert, raw_text="SL HIT")
    assert "SL hit" in card


def test_close_all_card():
    alert = FollowUpAlert(symbol=None, direction=None, action="close_all", raw_text="CLOSE ALL POSITION NOW")
    card = build_followup_card(alert, raw_text="CLOSE ALL POSITION NOW")
    assert "Close all positions" in card


def test_followup_card_hides_provider_details():
    raw = "TP3 HIT\n\nSignal Tag: #011/20260924\n\nPair: XAUUSD.\nTimeFrame: M5\nServer Time: 2026.09.24 11:25\n\nLevel Pri\n"
    alert = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text=raw, level=3)
    card = build_followup_card(alert, raw_text=raw)
    assert "Exit hit" in card
    assert "TP3 hit" not in card
    for leaked in ("Signal Tag", "TimeFrame", "Server Time", "Level Pri", "GEO", "Pair:"):
        assert leaked not in card
    assert "⏱" in card
    import re
    assert re.search(r"\d{1,2} \w{3} \d{1,2}:\d{2}(am|pm)", card)


def test_bot_token_missing_never_raises_send(monkeypatch):
    import core.forwarder as forwarder

    monkeypatch.setattr(forwarder, "BOT_TOKEN", "")
    assert forwarder.send_message("hello") is False