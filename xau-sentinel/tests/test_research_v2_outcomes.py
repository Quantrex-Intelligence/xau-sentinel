"""R-based outcomes: hand-built bars with known answers."""
import pandas as pd
import pytest

from backtest.research.outcomes_r import r_outcome, wilson


def _bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_buy_reaches_plus_one_then_plus_two_before_stop():
    # close 100, atr 2: +1R=102, +2R=104, -1R=98
    df = _bars([(100, 100.5, 99.5, 100),
                (100, 102.5, 99.8, 102.2),   # +1R hit
                (102, 104.5, 101.0, 104.0)])  # +2R hit
    out = r_outcome(df, 0, "BUY", atr=2.0, horizon=5)
    assert out.hit[1] and out.hit[2]
    assert not out.stop_first
    assert out.time_to_k[1] == 1 and out.time_to_k[2] == 2
    assert out.expectancy(2) == 2.0


def test_stop_before_target_scores_minus_one():
    df = _bars([(100, 100.5, 99.5, 100),
                (100, 100.6, 97.5, 98.0),   # -1R (98) first
                (98, 103.0, 97.0, 102.9)])  # later +2R does not count
    out = r_outcome(df, 0, "BUY", atr=2.0, horizon=5)
    assert out.stop_first
    assert not out.hit[2]
    assert out.expectancy(2) == -1.0
    assert out.outcome(2) == "loss"


def test_same_bar_touch_of_target_and_stop_is_a_loss():
    df = _bars([(100, 100.5, 99.5, 100),
                (100, 105.0, 95.0, 100)])  # touches +1R and -1R together
    out = r_outcome(df, 0, "BUY", atr=2.0, horizon=5)
    assert not out.hit[1]
    assert out.expectancy(1) == -1.0


def test_sell_mirrors_buy():
    df = _bars([(100, 100.5, 99.5, 100),
                (100, 100.5, 97.8, 98.0)])  # SELL +1R reached (98)
    out = r_outcome(df, 0, "SELL", atr=2.0, horizon=5)
    assert out.hit[1]
    assert out.expectancy(1) == 1.0


def test_timeout_scores_zero_and_is_not_a_win_or_loss():
    df = _bars([(100, 100.4, 99.6, 100), (100, 100.5, 99.5, 100.1)])
    out = r_outcome(df, 0, "BUY", atr=2.0, horizon=5)
    assert out.outcome(1) == "timeout"
    assert out.expectancy(1) == 0.0


def test_mfe_and_mae_are_in_r_units():
    df = _bars([(100, 100.5, 99.5, 100), (100, 103.0, 99.0, 102.0)])
    out = r_outcome(df, 0, "BUY", atr=2.0, horizon=5)
    assert out.mfe_r == pytest.approx(1.5)
    assert out.mae_r == pytest.approx(0.5)


def test_no_future_bars_means_no_outcome_and_no_lookahead():
    df = _bars([(100, 100.5, 99.5, 100)])
    out = r_outcome(df, 0, "BUY", atr=2.0, horizon=5)
    assert all(v is False for v in out.hit.values())
    assert out.outcome(1) == "timeout"


def test_invalid_atr_returns_none():
    df = _bars([(100, 100.5, 99.5, 100), (100, 101, 99, 100)])
    assert r_outcome(df, 0, "BUY", atr=0.0) is None
    assert r_outcome(df, 0, "BUY", atr=float("nan")) is None


def test_unknown_direction_is_rejected():
    df = _bars([(100, 100.5, 99.5, 100), (100, 101, 99, 100)])
    with pytest.raises(ValueError):
        r_outcome(df, 0, "HOLD", atr=2.0)


def test_wilson_interval_known_value():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3)
    assert hi == pytest.approx(0.5962, abs=1e-3)
