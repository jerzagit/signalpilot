"""Tests for core.autotrade (uses a fake MetaTrader5 module)."""

import types

import pytest

import core.autotrade as at


@pytest.fixture
def temp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "STATE_FILE", tmp_path / "autotrades.json")
    stubs = {"exits": [], "notices": []}
    monkeypatch.setattr(at, "notify_admin", lambda text: stubs["notices"].append(text))
    monkeypatch.setattr(at, "_sync_db", lambda *a, **k: None)
    monkeypatch.setattr(at, "mark_signal_exit", lambda sid, label: stubs["exits"].append((sid, label)))
    return stubs


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


def _trade(layers: int, tp1_done=False, tp2_done=False):
    tickets = list(range(1000, 1000 + layers))
    return {
        "source_id": "geom", "tag": "011/20260924", "symbol": "XAUUSD",
        "mt5_symbol": "XAUUSD-VIP", "direction": "sell", "entry": 4278.30,
        "fills": {str(t): 4278.30 for t in tickets}, "layers": layers,
        "volume0": round(layers * 0.01, 2), "tickets": tickets,
        "sl_geos": 4289.32, "open_ts": 0,
        "tps": [4273.30, 4270.30, 4267.30],
        "tp1_closed": at._stage_sizes(layers)[0] if tp1_done else 0,
        "tp1_sl_done": tp1_done, "tp1_done": tp1_done,
        "tp2_closed": at._stage_sizes(layers)[1] if tp2_done else 0,
        "tp2_done": tp2_done, "pending_action": None, "done": False,
    }


def _fake_positions(layers, vol=0.01):
    return [types.SimpleNamespace(
        magic=at.MAGIC, ticket=1000 + i, volume=vol,
        type=1, tp=4263.30, symbol="XAUUSD-VIP",
    ) for i in range(layers)]


def _mt5_harness(
    mt5,
    monkeypatch,
    live_layers,
    requests=None,
    fail_deal_tickets=None,
    fail_sltp_numbers=None,
):
    """Wire the fake MT5 module: positions, ticks, and a recording order_send."""
    _fake_mt5_constants(mt5)
    if requests is None:
        requests = []
    if fail_deal_tickets is None:
        fail_deal_tickets = set()
    if fail_sltp_numbers is None:
        fail_sltp_numbers = set()
    live_positions = _fake_positions(live_layers)
    sltp_count = 0
    monkeypatch.setattr(mt5, "positions_get", lambda *a, **k: list(live_positions))

    def order_send(request, **kwargs):
        nonlocal sltp_count
        requests.append(request)
        if request["action"] == mt5.TRADE_ACTION_DEAL:
            ticket = request.get("position")
            if ticket in fail_deal_tickets:
                return types.SimpleNamespace(retcode=10015, order=0, comment="failed")
            live_positions[:] = [pos for pos in live_positions if pos.ticket != ticket]
        else:
            sltp_count += 1
            if sltp_count in fail_sltp_numbers:
                return types.SimpleNamespace(retcode=10015, order=0, comment="failed")
        return types.SimpleNamespace(
            retcode=mt5.TRADE_RETCODE_DONE, order=9999, comment="ok"
        )

    monkeypatch.setattr(
        mt5, "symbol_info_tick",
        lambda s: types.SimpleNamespace(bid=4263.10, ask=4263.30),
    )
    monkeypatch.setattr(mt5, "order_send", order_send)
    return requests


def test_tag_from_extracts_signal_tag():
    assert at._tag_from("TP1 HIT\n\nSignal Tag: #011/20260924") == "011/20260924"
    assert at._tag_from("no tag here") == "unknown"


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


def test_stage_sizes():
    assert at._stage_sizes(0) == (0, 0, 0)
    assert at._stage_sizes(1) == (0, 0, 1)
    assert at._stage_sizes(2) == (1, 0, 1)
    assert at._stage_sizes(3) == (1, 1, 1)
    assert at._stage_sizes(4) == (2, 1, 1)
    assert at._stage_sizes(5) == (2, 1, 2)
    assert at._stage_sizes(8) == (4, 2, 2)


def test_manage_tp1_closes_half_and_anchors_sl(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(5)}
    requests = _mt5_harness(mt5, monkeypatch, live_layers=5)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=1)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert trade["tp1_done"] is True
    assert trade["done"] is False
    assert result == "TP1: closed 0.02 of 0.05 (2/5 layers)"
    # half closed (two DEAL closes) then TP1-breakeven set on the runner
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    sltps = [r for r in requests if r["action"] == mt5.TRADE_ACTION_SLTP]
    assert len(deals) == 2
    assert len(sltps) == 3
    assert all(r["sl"] == 4273.30 for r in sltps)


def test_manage_tp1_single_layer_holds_and_anchors_sl(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(1)}
    requests = _mt5_harness(mt5, monkeypatch, live_layers=1)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=1)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "TP1: single layer, holding to TP2"
    assert trade["tp1_done"] is True
    assert trade["done"] is False
    sltps = [r for r in requests if r["action"] == mt5.TRADE_ACTION_SLTP]
    assert sltps and all(r["sl"] == 4273.30 for r in sltps)


def test_legacy_tp1_state_anchors_sl_without_reclosing(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    trade = _trade(5)
    trade["tp1_done"] = True
    trade.pop("tp1_closed")
    trade.pop("tp1_sl_done")
    requests = _mt5_harness(mt5, monkeypatch, live_layers=3)

    assert at._close_at_price_targets(trade, (4273.10, 4273.30)) is True
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    sltps = [r for r in requests if r["action"] == mt5.TRADE_ACTION_SLTP]
    assert trade["tp1_closed"] == 2
    assert trade["tp1_sl_done"] is True
    assert not deals
    assert len(sltps) == 3


def test_tp1_retries_sl_without_reclosing_layers(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    trade = _trade(5)
    fail_sltp = {1}
    requests = _mt5_harness(
        mt5, monkeypatch, live_layers=5, fail_sltp_numbers=fail_sltp
    )

    assert at._release_stage("XAUUSD-VIP", trade, 1) == "TP1: SL update pending"
    assert trade["tp1_closed"] == 2
    assert trade["tp1_sl_done"] is False
    assert trade["tp1_done"] is False
    fail_sltp.clear()
    assert at._release_stage("XAUUSD-VIP", trade, 1) == (
        "TP1: released 2/5 layers; SL set at TP1"
    )
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    sltps = [r for r in requests if r["action"] == mt5.TRADE_ACTION_SLTP]
    assert trade["tp1_sl_done"] is True
    assert trade["tp1_done"] is True
    assert len(deals) == 2
    assert len(sltps) == 6


def test_partial_tp1_protects_runner_and_blocks_out_of_order_tp2(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(5)}
    trade = state["geom:011/20260924"]
    fail_deal = {1001, 1002, 1003, 1004}
    requests = _mt5_harness(
        mt5, monkeypatch, live_layers=5, fail_deal_tickets=fail_deal
    )

    assert at._release_stage("XAUUSD-VIP", trade, 1) == (
        "TP1: closed 0.01 of 0.05 (1/5 layers); close pending"
    )
    assert trade["tp1_closed"] == 1
    assert trade["tp1_sl_done"] is True
    assert trade["tp1_done"] is False
    assert trade["pending_action"] == "tp1"

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    assert at._manage(state, "geom:011/20260924", trade, fu) == (
        "AUTO: waiting for tp1"
    )

    fail_deal.clear()
    assert at._release_stage("XAUUSD-VIP", trade, 1) == (
        "TP1: released 2/5 layers; SL set at TP1"
    )
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    sltps = [r for r in requests if r["action"] == mt5.TRADE_ACTION_SLTP]
    assert trade["tp1_closed"] == 2
    assert trade["tp1_done"] is True
    assert trade.get("pending_action") is None
    assert len(deals) == 6
    assert len(sltps) == 4


def test_exit_message_supersedes_pending_lower_stage(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(5)}
    trade = state["geom:011/20260924"]
    trade.update({"tp1_closed": 1, "tp1_sl_done": True, "pending_action": "tp1"})
    requests = _mt5_harness(mt5, monkeypatch, live_layers=4)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=3)
    result = at._manage(state, "geom:011/20260924", trade, fu)
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert result == "Exit: closed 0.04"
    assert trade["done"] is True
    assert trade["exit_price"] == "Exit"
    assert trade.get("pending_action") is None
    assert len(deals) == 4


def test_two_layer_pending_tp1_does_not_make_tp2_terminal(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(2)}
    trade = state["geom:011/20260924"]
    trade.update({"tp1_closed": 1, "tp1_sl_done": True, "pending_action": "tp1"})
    _mt5_harness(mt5, monkeypatch, live_layers=1)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "AUTO: waiting for tp1"
    assert trade["done"] is False
    assert trade.get("exit_price", "") == ""


def test_single_layer_tp2_supersedes_pending_tp1_message(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(1)}
    trade = state["geom:011/20260924"]
    trade.update({"tp1_sl_done": True, "pending_action": "tp1"})
    requests = _mt5_harness(mt5, monkeypatch, live_layers=1)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    result = at._manage(state, "geom:011/20260924", trade, fu)
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert result == "TP2: closed 0.01"
    assert trade["done"] is True
    assert trade["exit_price"] == "TP2"
    assert trade.get("pending_action") is None
    assert len(deals) == 1


def test_price_tp2_supersedes_pending_tp1_for_single_layer(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    trade = _trade(1)
    trade.update({"tp1_sl_done": True, "pending_action": "tp1"})
    requests = _mt5_harness(mt5, monkeypatch, live_layers=1)

    assert at._close_at_price_targets(trade, (4266.0, 4266.2)) is True
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert trade["done"] is True
    assert trade["exit_price"] == "TP2"
    assert trade.get("pending_action") is None
    assert len(deals) == 1


def test_price_exit_supersedes_pending_lower_stage(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    trade = _trade(8)
    trade.update({"tp1_closed": 2, "tp1_sl_done": True, "pending_action": "tp1"})
    requests = _mt5_harness(mt5, monkeypatch, live_layers=6)

    assert at._close_at_price_targets(trade, (4267.10, 4267.30)) is True
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert trade["done"] is True
    assert trade["exit_price"] == "Exit"
    assert trade.get("pending_action") is None
    assert len(deals) == 6


def test_manage_tp2_closes_quarter_not_all(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(5, tp1_done=True)}
    # 2 layers already closed on TP1 -> 3 left live; TP2 takes the ~quarter (1)
    _mt5_harness(mt5, monkeypatch, live_layers=3)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "TP2: closed 0.01 (1/5 layers)"
    assert trade["tp2_done"] is True
    assert trade["done"] is False


def test_tp2_retries_only_unclosed_layers(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    trade = _trade(8, tp1_done=True)
    fail_deal = {1001, 1002, 1003}
    requests = _mt5_harness(
        mt5, monkeypatch, live_layers=4, fail_deal_tickets=fail_deal
    )

    assert at._release_stage("XAUUSD-VIP", trade, 2) == (
        "TP2: closed 0.01 (1/8 layers); close pending"
    )
    assert trade["tp2_closed"] == 1
    assert trade["tp2_done"] is False
    fail_deal.clear()
    assert at._release_stage("XAUUSD-VIP", trade, 2) == (
        "TP2: released 2/8 layers"
    )
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert trade["tp2_closed"] == 2
    assert trade["tp2_done"] is True
    assert len(deals) == 5


def test_tp2_price_then_message_closes_once(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(8, tp1_done=True)}
    requests = _mt5_harness(mt5, monkeypatch, live_layers=4)

    from core.signal import FollowUpAlert

    trade = state["geom:011/20260924"]
    assert at._close_at_price_targets(trade, (4270.10, 4270.30)) is True
    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    result = at._manage(state, "geom:011/20260924", trade, fu)
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert result == "TP2: already scaled out"
    assert trade["tp2_done"] is True
    assert trade["done"] is False
    assert len(deals) == 2
    assert temp_state["notices"] == [
        "💰 AUTO TP2: closed 0.02 (2/8 layers) — XAUUSD-VIP [tag 011/20260924]",
    ]


def test_manage_unknown_tp_level_does_not_close(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(5)}
    requests = _mt5_harness(mt5, monkeypatch, live_layers=5)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=0)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert result == "unrecognized TP level: 0"
    assert trade["tp1_done"] is False
    assert trade["tp2_done"] is False
    assert trade["done"] is False
    assert not deals


def test_manage_tp2_two_layers_holds_to_exit(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(2, tp1_done=True)}
    requests = _mt5_harness(mt5, monkeypatch, live_layers=1)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "TP2: holding to Exit"
    assert trade["tp2_done"] is True
    assert trade["done"] is False
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert not deals


def test_manage_exit_closes_rest_and_records_exit(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(5, tp1_done=True, tp2_done=True)}
    # 2 layers left after TP1+TP2 -> closed here at Exit
    _mt5_harness(mt5, monkeypatch, live_layers=2)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=3)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "Exit: closed 0.02"
    assert trade["done"] is True
    assert trade["exit_price"] == "Exit"
    assert temp_state["exits"] == [("011/20260924", "Exit")]


def test_exit_retries_failed_close_before_marking_done(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    trade = _trade(2, tp1_done=True)
    fail_deal = {1000}
    requests = _mt5_harness(
        mt5, monkeypatch, live_layers=1, fail_deal_tickets=fail_deal
    )

    assert at._release_stage("XAUUSD-VIP", trade, 3) == (
        "Exit: closed 0; close pending"
    )
    assert trade["done"] is False
    fail_deal.clear()
    assert at._release_stage("XAUUSD-VIP", trade, 3) == "Exit: closed 0.01"
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert trade["done"] is True
    assert trade["exit_price"] == "Exit"
    assert len(deals) == 2


def test_manage_tp2_single_layer_closes_all(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    state = {"geom:011/20260924": _trade(1, tp1_done=True)}
    _mt5_harness(mt5, monkeypatch, live_layers=1)

    from core.signal import FollowUpAlert

    fu = FollowUpAlert(symbol="XAUUSD", direction="sell", action="tp_hit", raw_text="", level=2)
    trade = state["geom:011/20260924"]
    result = at._manage(state, "geom:011/20260924", trade, fu)
    assert result == "TP2: closed 0.01"
    assert trade["done"] is True
    assert temp_state["exits"] == [("011/20260924", "TP2")]


def test_monitor_retries_pending_close_all_from_saved_state(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    trade = _trade(2)
    trade["pending_action"] = "close_all"
    at._save({"geom:011/20260924": trade})
    fail_deal = {1000}
    requests = _mt5_harness(
        mt5, monkeypatch, live_layers=2, fail_deal_tickets=fail_deal
    )
    monkeypatch.setattr(at, "AUTOTRADE_ENABLED", True)
    monkeypatch.setattr(at, "_ready", lambda: True)

    at._monitor_prices()
    saved = at._state()["geom:011/20260924"]
    assert saved["done"] is False
    assert saved["pending_action"] == "close_all"

    fail_deal.clear()
    at._monitor_prices()
    saved = at._state()["geom:011/20260924"]
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert saved["done"] is True
    assert saved.get("pending_action") is None
    assert saved["exit_price"] == "MAN"
    assert len(deals) == 3
    assert temp_state["exits"] == [("011/20260924", "MAN")]


def test_monitor_migrates_legacy_tp1_state_without_price_close(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    trade = _trade(5)
    trade["tp1_done"] = True
    trade.pop("tp1_closed")
    trade.pop("tp1_sl_done")
    at._save({"geom:011/20260924": trade})
    requests = _mt5_harness(mt5, monkeypatch, live_layers=3)
    monkeypatch.setattr(at, "AUTOTRADE_ENABLED", True)
    monkeypatch.setattr(at, "PRICE_TP_CLOSE", False)
    monkeypatch.setattr(at, "_ready", lambda: True)

    at._monitor_prices()
    saved = at._state()["geom:011/20260924"]
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    sltps = [r for r in requests if r["action"] == mt5.TRADE_ACTION_SLTP]
    assert saved["tp1_closed"] == 2
    assert saved["tp1_sl_done"] is True
    assert saved["tp1_done"] is True
    assert not deals
    assert len(sltps) == 3


def test_monitor_retries_partial_tp2_after_tp1_is_done(
    monkeypatch, temp_state
):
    import MetaTrader5 as mt5

    trade = _trade(8, tp1_done=True)
    trade["tp2_closed"] = 1
    trade["tp2_done"] = False
    at._save({"geom:011/20260924": trade})
    requests = _mt5_harness(mt5, monkeypatch, live_layers=7)
    monkeypatch.setattr(at, "AUTOTRADE_ENABLED", True)
    monkeypatch.setattr(at, "PRICE_TP_CLOSE", False)
    monkeypatch.setattr(at, "_ready", lambda: True)

    at._monitor_prices()
    saved = at._state()["geom:011/20260924"]
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert saved["tp2_closed"] == 2
    assert saved["tp2_done"] is True
    assert saved.get("pending_action") is None
    assert len(deals) == 1


def test_tp_arrival_notifies_each_level_once(monkeypatch, temp_state):
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

    # jump past TP2 and Exit -> pings for TP2 and Exit only
    tick2 = (4281.50, 4281.70)
    assert at._notify_tp_if_reached(trade, tick2) is True
    assert trade.get("tp2_notified") is True
    assert trade.get("tp3_notified") is True
    assert len(calls) == 3
    assert "TP1 reached" in calls[0]
    assert "TP2 reached" in calls[1]
    assert "Exit reached" in calls[2]


def test_price_jump_to_exit_stages_all_levels(monkeypatch, temp_state):
    import MetaTrader5 as mt5

    trade = _trade(8)  # sell; tps 4273.30 / 4270.30 / 4267.30
    requests = _mt5_harness(mt5, monkeypatch, live_layers=8)

    # price already past all three targets
    tick = (4267.10, 4267.30)
    assert at._close_at_price_targets(trade, tick) is True
    assert trade["tp1_done"] is True
    assert trade["tp2_done"] is True
    assert trade["done"] is True
    assert trade["exit_price"] == "Exit"
    deals = [r for r in requests if r["action"] == mt5.TRADE_ACTION_DEAL]
    assert len(deals) == 8
    assert temp_state["notices"] == [
        "💰 AUTO TP1: closed 0.04 of 0.08 (4/8 layers) — XAUUSD-VIP [tag 011/20260924]",
        "💰 AUTO TP2: closed 0.02 (2/8 layers) — XAUUSD-VIP [tag 011/20260924]",
        "💰 AUTO Exit: closed 0.02 — XAUUSD-VIP [tag 011/20260924]",
    ]
    # the Exit record is written by the price monitor (mark_signal_exit), not here