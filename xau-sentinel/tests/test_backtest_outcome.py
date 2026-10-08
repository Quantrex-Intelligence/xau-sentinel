"""The backtest labeler must be right before it can grade the engine."""
import pandas as pd
import pytest

from backtest.outcome import label_signal


def _bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_buy_target_hit_first_is_a_win():
    # entry close 100, atr 2 -> target 102, stop 98
    df = _bars([
        (100, 100.5, 99.5, 100),  # signal bar
        (100, 101.0, 99.8, 100.8),
        (100.8, 102.5, 100.5, 102.2),  # high reaches 102 first
    ])
    assert label_signal(df, 0, "BUY", atr=2.0, horizon=5).outcome == "win"


def test_buy_stop_hit_first_is_a_loss():
    df = _bars([
        (100, 100.5, 99.5, 100),
        (100, 100.5, 97.5, 98.0),  # low reaches 98 first
        (98, 103.0, 97.0, 102.5),
    ])
    assert label_signal(df, 0, "BUY", atr=2.0, horizon=5).outcome == "loss"


def test_sell_target_hit_first_is_a_win():
    df = _bars([
        (100, 100.5, 99.5, 100),
        (100, 100.2, 97.5, 97.8),  # low reaches 98 = target for SELL
    ])
    assert label_signal(df, 0, "SELL", atr=2.0, horizon=5).outcome == "win"


def test_sell_stop_hit_first_is_a_loss():
    df = _bars([
        (100, 100.5, 99.5, 100),
        (100, 102.5, 99.8, 102.2),  # high reaches 102 = stop for SELL
    ])
    assert label_signal(df, 0, "SELL", atr=2.0, horizon=5).outcome == "loss"


def test_no_level_reached_within_horizon_is_a_timeout():
    df = _bars([
        (100, 100.5, 99.5, 100),
        (100, 100.9, 99.1, 100.1),
        (100.1, 101.0, 99.2, 100.2),
    ])
    assert label_signal(df, 0, "BUY", atr=2.0, horizon=2).outcome == "timeout"


def test_both_levels_in_one_bar_is_conservatively_a_loss():
    df = _bars([
        (100, 100.5, 99.5, 100),
        (100, 103.0, 97.0, 100),  # touches target AND stop; order unknown
    ])
    assert label_signal(df, 0, "BUY", atr=2.0, horizon=5).outcome == "loss"


def test_horizon_stops_at_end_of_data_without_error():
    df = _bars([(100, 100.5, 99.5, 100), (100, 100.9, 99.2, 100.1)])
    assert label_signal(df, 0, "BUY", atr=2.0, horizon=48).outcome == "timeout"


def test_unknown_direction_is_rejected():
    df = _bars([(100, 100.5, 99.5, 100), (100, 100.9, 99.2, 100.1)])
    with pytest.raises(ValueError):
        label_signal(df, 0, "HOLD", atr=2.0)
