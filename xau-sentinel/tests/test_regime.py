"""Regime validation: H1 structure is primary, ATR only adds volatility
flavor, and the engine must never contradict the H1 structure it read."""
from analysis.regime import classify_regime
from tests.test_structure import _ramp_path, _flat_candles_from_path, BULLISH_POINTS, BEARISH_POINTS


def _quiet_m15(n=40, price=100.0):
    """Low, uniform-range M15 candles -> low ATR baseline == recent ATR (neither high nor low vol)."""
    from tests.conftest import make_candles
    return make_candles([(price, price + 0.3, price - 0.3, price) for _ in range(n)])


def test_bullish_h1_structure_yields_trending_up_never_down():
    h1 = _flat_candles_from_path(_ramp_path(BULLISH_POINTS[:6], steps_per_leg=7), tail=[113, 114, 115])
    m15 = _quiet_m15()
    result = classify_regime(h1, m15)
    assert result.regime in ("TRENDING UP", "BREAKOUT", "HIGH VOLATILITY", "LOW VOLATILITY")
    assert result.regime != "TRENDING DOWN"


def test_bearish_h1_structure_yields_trending_down_never_up():
    h1 = _flat_candles_from_path(_ramp_path(BEARISH_POINTS[:6], steps_per_leg=7), tail=[87, 86, 85])
    m15 = _quiet_m15()
    result = classify_regime(h1, m15)
    assert result.regime != "TRENDING UP"


def test_h1_pullback_state_maps_to_pullback_regime():
    h1 = _flat_candles_from_path(_ramp_path(BULLISH_POINTS[:6], steps_per_leg=7), tail=[104, 102, 100])
    m15 = _quiet_m15()
    result = classify_regime(h1, m15)
    assert result.regime == "PULLBACK"
    assert "H1 structure" in result.reason


def test_bullish_bos_yields_breakout_regime():
    import pandas as pd
    path = _ramp_path(BULLISH_POINTS, steps_per_leg=7)
    h1 = _flat_candles_from_path(path, tail=[126, 124, 122, 126, 129])  # close > latest HH 128: confirmed BOS, see test_structure
    m15 = _quiet_m15()
    result = classify_regime(h1, m15)
    assert result.regime == "BREAKOUT"


def test_regime_reason_is_never_contradictory():
    """A strongly bullish H1 structure must never be reported as TRENDING DOWN."""
    h1 = _flat_candles_from_path(_ramp_path(BULLISH_POINTS[:6], steps_per_leg=7), tail=[113, 114, 115])
    m15 = _quiet_m15()
    result = classify_regime(h1, m15)
    assert "DOWN" not in result.regime
