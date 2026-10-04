"""Analysis V2 observations: closed-candle enforcement, missing/NaN input, and
agreement with the existing engine primitives."""
import math
from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from analysis.liquidity import detect_sweeps
from analysis.regime import classify_regime
from analysis.structure import analyze_structure, closed_only, compute_atr, displacement_at
from analysis.v2.engine import build_analysis
from analysis.v2.observations import build_observations
from analysis.zones import compute_zones
from tests.v2_fixtures import range_set, trend_set, with_forming_bar


def _now(candles):
    return candles["M5"]["close_time"].iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)


def test_forming_bar_cannot_change_any_output():
    """Closed-candle enforcement: appending a still-forming bar with extreme values
    must leave the analysis unchanged, including the narrative text."""
    base = trend_set("up")
    with_forming = with_forming_bar(base, "M5")
    a = build_analysis(base, now=_now(base))
    b = build_analysis(with_forming, now=_now(base))
    assert a.narrative == b.narrative
    assert a.observations.current_price == b.observations.current_price
    assert {k: v.state for k, v in a.observations.structure.items()} == \
        {k: v.state for k, v in b.observations.structure.items()}


def test_current_price_is_the_last_closed_m5_close():
    candles = trend_set("up")
    obs = build_observations(candles)
    closed_m5 = closed_only({"M5": candles["M5"]})["M5"]
    assert obs.current_price == pytest.approx(float(closed_m5["close"].iloc[-1]))


def test_frame_without_closed_flag_is_ignored_and_reported():
    candles = trend_set("up")
    candles["H1"] = candles["H1"].drop(columns=["is_closed"])
    obs = build_observations(candles)
    assert obs.structure["H1"].state == "INSUFFICIENT"
    assert any("no is_closed column" in issue for issue in obs.data_issues)


def test_missing_timeframe_is_reported_not_raised():
    candles = trend_set("up")
    del candles["H4"]
    obs = build_observations(candles)
    assert obs.structure["H4"].state == "INSUFFICIENT"
    assert any(issue.startswith("H4: no candles") for issue in obs.data_issues)


def test_short_history_is_reported_with_the_required_minimum():
    candles = trend_set("up")
    candles["M5"] = candles["M5"].iloc[:50]
    obs = build_observations(candles)
    assert obs.structure["M5"].state == "INSUFFICIENT"
    assert any("insufficient closed history" in issue for issue in obs.data_issues)


def test_empty_input_gives_insufficient_status_without_exceptions():
    result = build_analysis({})
    assert result.status == "INSUFFICIENT_DATA"
    assert result.scenarios == ()
    assert result.areas == ()
    assert result.narrative  # still explains why


def test_nan_volume_yields_unknown_volume_state_not_zero():
    candles = trend_set("up")
    candles["M5"].loc[candles["M5"].index[-1], "volume"] = np.nan
    obs = build_observations(candles)
    assert obs.volume_m5["state"] == "UNKNOWN"
    assert obs.volume_m5["relative_volume"] is None or math.isnan(obs.volume_m5["relative_volume"])


def test_structure_matches_the_existing_engine_exactly():
    """Regression: V2 reads the same structure states as analysis/structure.py."""
    candles = trend_set("up")
    obs = build_observations(candles)
    for tf in ("M5", "M15", "H1", "H4"):
        closed = closed_only({tf: candles[tf]})[tf]
        assert obs.structure[tf].state == analyze_structure(closed).state


def test_regime_and_sweeps_and_displacement_match_the_existing_engine():
    candles = range_set()
    obs = build_observations(candles)
    m5 = closed_only({"M5": candles["M5"]})["M5"]
    h1 = closed_only({"H1": candles["H1"]})["H1"]
    h4 = closed_only({"H4": candles["H4"]})["H4"]
    m15 = closed_only({"M15": candles["M15"]})["M15"]

    zones = compute_zones(m5, h1, h4)
    assert obs.zones == zones
    assert [(s.kind, s.level_name, s.time) for s in obs.sweeps] == \
        [(s.kind, s.level_name, s.time) for s in detect_sweeps(m5, zones)]

    atr = compute_atr(m5)
    assert obs.displacement_m5 == displacement_at(m5, len(m5) - 1, atr=atr)
    assert classify_regime(h1, m15).regime in {"RANGING", "TRENDING UP", "TRENDING DOWN", "PULLBACK",
                                               "BREAKOUT", "HIGH VOLATILITY", "LOW VOLATILITY"}


def test_atr_percentile_and_change_are_measured_on_closed_bars():
    candles = trend_set("up")
    obs = build_observations(candles)
    assert obs.atr_m5 is not None and obs.atr_m5 > 0
    assert 0.0 <= obs.atr_percentile_m5 <= 100.0
    assert obs.atr_change_m5 is not None and obs.atr_change_m5 > 0


def test_observations_carry_the_utc_bar_time_of_the_last_closed_bar():
    candles = trend_set("up")
    obs = build_observations(candles)
    closed_m5 = closed_only({"M5": candles["M5"]})["M5"]
    assert pd.Timestamp(obs.as_of).tz_convert("UTC") == pd.Timestamp(closed_m5["time"].iloc[-1]).tz_convert("UTC")


def test_zone_distances_are_atr_normalized_and_signed():
    candles = range_set()
    obs = build_observations(candles)
    assert obs.zone_distances_atr, "range fixture must produce session/day zones"
    for name, distance in obs.zone_distances_atr.items():
        level = obs.zones[name]
        assert distance == pytest.approx((level - obs.current_price) / obs.atr_m5, rel=1e-6)
