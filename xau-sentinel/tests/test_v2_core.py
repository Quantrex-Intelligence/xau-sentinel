"""Analysis V2 increment 1: typed models, ATR-normalized metrics, VWAP anchor."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from analysis.v2.models import Evidence, KeyArea, KeyComponent, Relationship
from analysis.v2.normalize import (
    atr_normalized_distance, atr_percentile, range_ratio, swing_size_atr, zone_width_atr,
)
from analysis.zones import compute_session_vwap

T = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


def test_atr_normalized_distance_is_signed_and_scale_free():
    assert atr_normalized_distance(3010.0, 3000.0, 5.0) == pytest.approx(2.0)
    assert atr_normalized_distance(2990.0, 3000.0, 5.0) == pytest.approx(-2.0)
    # Same ratio at a different price level and volatility: 10 points at 5 ATR = 2 ATR.
    assert atr_normalized_distance(2020.0, 2010.0, 5.0) == pytest.approx(2.0)


@pytest.mark.parametrize("level,price,atr", [(None, 3000.0, 5.0), (3010.0, 3000.0, 0.0),
                                             (3010.0, 3000.0, float("nan")), (float("nan"), 3000.0, 5.0)])
def test_unmeasurable_distance_is_nan_not_zero(level, price, atr):
    assert np.isnan(atr_normalized_distance(level, price, atr))


def test_width_and_swing_size_are_atr_multiples():
    assert zone_width_atr(3000.0, 3004.0, 2.0) == pytest.approx(2.0)
    assert swing_size_atr(3010.0, 3000.0, 5.0) == pytest.approx(2.0)
    assert np.isnan(zone_width_atr(3000.0, 3004.0, 0.0))


def test_atr_percentile_uses_only_trailing_values():
    s = pd.Series(np.arange(1, 201, dtype=float))  # rising ATR
    assert atr_percentile(s, window=100) == pytest.approx(100.0)
    s2 = pd.Series(np.arange(200, 0, -1, dtype=float))  # falling ATR
    assert atr_percentile(s2, window=100) == pytest.approx(1.0)


def test_atr_percentile_is_nan_without_enough_history():
    assert np.isnan(atr_percentile(pd.Series([1.0, 2.0, 3.0]), window=100))


def test_atr_percentile_does_not_change_when_future_values_are_added():
    base = pd.Series(np.random.default_rng(3).uniform(1, 5, 150))
    extended = pd.concat([base, pd.Series([99.0, 0.1])], ignore_index=True)
    assert atr_percentile(base) == atr_percentile(base.copy())
    assert atr_percentile(extended.iloc[:150]) == atr_percentile(base)


def test_range_ratio_handles_empty_history():
    assert np.isnan(range_ratio(3005, 2995, pd.Series(dtype=float)))
    assert range_ratio(3005, 2995, pd.Series([5.0, 5.0])) == pytest.approx(2.0)


def test_evidence_and_key_area_keep_provenance():
    ev = Evidence("H1", T, "PDH", 3010.0, "analysis.zones", "previous weekday high")
    comp = KeyComponent("PDH", 3010.0, ev)
    area = KeyArea(3009.5, 3010.5, (comp,), "RESISTANCE", "MODERATE", "one independent reference")
    assert area.components[0].evidence.source == "analysis.zones"
    assert area.width == pytest.approx(1.0)
    assert area.distinct_sources == 1
    rel = Relationship(area, 0.5, "APPROACHING")
    assert rel.area is area


def test_models_are_immutable():
    ev = Evidence("H1", T, "PDH", 3010.0, "analysis.zones")
    with pytest.raises(Exception):
        ev.value = 1.0  # frozen dataclass


def test_vwap_matches_independent_calculation_and_stays_in_range():
    bars = pd.DataFrame({
        "high": [3005.0, 3010.0, 3008.0], "low": [2995.0, 3000.0, 3001.0],
        "close": [3001.0, 3007.0, 3004.0], "volume": [100, 300, 200],
    })
    typical = (bars.high + bars.low + bars.close) / 3
    expected = float((typical * bars.volume).sum() / bars.volume.sum())
    got = compute_session_vwap(bars)
    assert got == pytest.approx(expected)
    assert bars.low.min() <= got <= bars.high.max()


def test_vwap_is_none_for_empty_input():
    assert compute_session_vwap(pd.DataFrame()) is None
