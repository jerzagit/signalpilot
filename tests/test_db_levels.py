"""Pure-function checks for target/exit level labelling in core.db."""

from core.db import close_level


def test_buy_close_level_labels():
    tps = [4336.0, 4341.0, 4346.0]
    assert close_level(4337.0, tps, 4320.0, "buy") == "TP1"
    assert close_level(4342.0, tps, 4320.0, "buy") == "TP2"
    assert close_level(4346.2, tps, 4320.0, "buy") == "Exit"


def test_sell_close_level_labels():
    tps = [4305.0, 4300.0, 4295.0]
    assert close_level(4304.0, tps, 4322.0, "sell") == "TP1"
    assert close_level(4299.0, tps, 4322.0, "sell") == "TP2"
    assert close_level(4294.8, tps, 4322.0, "sell") == "Exit"


def test_close_level_sl_and_manual():
    tps = [4336.0, 4341.0, 4346.0]
    assert close_level(4320.0, tps, 4320.0, "buy") == "SL"
    assert close_level(4330.0, tps, 4320.0, "buy") == "MAN"


def test_close_level_beyond_three_targets():
    tps = [4336.0, 4341.0, 4346.0, 4351.0]
    assert close_level(4337.0, tps, 4320.0, "buy") == "TP1"
    assert close_level(4346.2, tps, 4320.0, "buy") == "Exit"
    assert close_level(4352.0, tps, 4320.0, "buy") == "TP4"