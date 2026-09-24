"""Tests for core.autotrade (uses a fake MetaTrader5 module)."""

import types

import pytest

import core.autotrade as at


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "STATE_FILE", tmp_path / "autotrades.json")


def _fake_mt5_constants(mt5):
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_ACTION_SLTP = 6
    mt5.ORDER_TIME_GTC = 0
    mt5.ORDER_FILLING_IOC = 2
    mt5.POSITION_TYPE_BUY = 0
    mt5.POSITION_TYPE_SELL = 1


def _trade(layers: int, be_done=True, tp1_done=False):
    tickets = list(range(1000, 1000 + layers))
    return {
        "source_id": "geom", "tag": "011/20260924", "symbol": "XAUUSD",
        "mt5_symbol": "XAUUSD-VIP", "direction": "sell", "entry": 4278.30,
        "fills": {str(t): 4278.30 for t in tickets}, "layers": layers,
        "volume0": round(layers * 0.01, 2), "tickets": tickets,
        "sl_geos": 4289.32, "open_ts": 0, "be_done": be_done,
        "tp1_done": tp1_done, "done": False,
    }


def _fake_positions(layers, vol=0.01):
    return [types.SimpleNamespace(
        magic=at.MAGIC, ticket=1000 + i, volume=vol,
        type=1, tp=4263.30, symbol="XAUUSD-VIP",
    ) for i in range(layers)]


def test_tag_from_extracts_signal_tag():
    assert at._tag_from("TP1 HIT\n\nSignal Tag: #011/20260924") == "011/20260924"
    assert at._tag_from("no tag here") == "unknown"


def test_symbol_pip_cfg_default():
    from core.config import PIP_SIZE

    assert at.symbol_pip("XAUUSD-VIP") == PIP_SIZE["XAUUSD-VIP"] == 0.10


def test_symbol_map():
    assert at.mt5_symbol("XAUUSD") == "XAUUSD-VIP"
    assert at.mt5_symbol("EURUSD") == "EURUSD"  # unmapped passes through


def test_calc_layers_by_margin(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    _fake_mt5_constants(mt5)
    monkeypatch.setattr(mt5, "order_calc_margin", lambda ot, s, lot, price: 30.0)
    monkeypatch.setattr(
        mt5, "symbol_info_tick",
        lambda s: types.SimpleNamespace(bid=4278.10, ask=4278.30),
    )
    monkeypatch.setattr(
        mt5, "symbol_info",
        lambda s: types.SimpleNamespace(digits=2, volume_step=0.01, volume_max=100.0),
    )
    # 5% of 10000 = 500 -> 16 layers of 0.01 (margin 30 each)
    assert at.calc_layers("XAUUSD-VIP", "sell", 10000.0) == 16
    assert at.calc_layers("XAUUSD-VIP", "buy", 100.0) == 0


def test_manage_tp1_closes_half_the_layers(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    _fake_mt5_constants(mt5)
    state = {"geom:011/20260924": _trade(5)}
    monkeypatch.setattr(mt5, "positions_get", lambda *a, **k: _fake_positions(5))
    monkeypatch.setattr(
        mt5, "symbol_info_tick",
        lambda s: types.SimpleNamespace(bid=4273.10, ask=4273.30),
    )
    monkeypatch.setattr(
        mt5, "order_send",
        lambda r, **k: types.SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=9999, comment="ok"),
    )

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=1)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert trade["tp1_done"] is True
    assert trade["done"] is False
    # 5 layers -> half = 2 layers closed (0.02)
    assert result == "TP1: closed 0.02 of 0.05 (2/5 layers)"


def test_manage_tp1_single_layer_holds(monkeypatch, temp_state):
    state = {"geom:011/20260924": _trade(1)}
    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=1)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "TP1: single layer, holding to TP2"
    assert trade["done"] is False


def test_manage_tp2_closes_remaining_layers(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    _fake_mt5_constants(mt5)
    state = {"geom:011/20260924": _trade(5, tp1_done=True)}
    # 2 layers already closed on TP1 -> 3 left live
    monkeypatch.setattr(mt5, "positions_get", lambda *a, **k: _fake_positions(3))
    monkeypatch.setattr(
        mt5, "symbol_info_tick",
        lambda s: types.SimpleNamespace(bid=4263.10, ask=4263.30),
    )
    monkeypatch.setattr(
        mt5, "order_send",
        lambda r, **k: types.SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=9999, comment="ok"),
    )

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "TP2: closed 0.03"
    assert trade["done"] is True


def test_tp_arrival_notifies_each_level_once(monkeypatch, temp_state, capsys):
    trade = _trade(8)
    trade["direction"] = "buy"
    trade["tps"] = [4270.88, 4275.88, 4280.88]
    calls = []
    monkeypatch.setattr(at, "notify_admin", lambda text: calls.append(text))

    # price already past TP1 -> only TP1 flagged
    tick = (4272.00, 4272.30)
    assert at._notify_tp_if_reached(trade, tick) is True
    assert trade.get("tp1_notified") is True
    assert trade.get("tp2_notified", False) is False
    assert len(calls) == 1

    # same price again -> no duplicate
    assert at._notify_tp_if_reached(trade, tick) is False
    assert len(calls) == 1

    # jump past TP2 as well -> new ping only for TP2
    tick2 = (4281.50, 4281.70)
    assert at._notify_tp_if_reached(trade, tick2) is True
    assert trade.get("tp2_notified") is True
    assert trade.get("tp3_notified") is True
    assert len(calls) == 3