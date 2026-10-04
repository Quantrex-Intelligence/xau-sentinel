"""Volume features (Analysis Engine V2, increment 3).

Source: MT5 tick_volume, exposed as the `volume` column. real_volume is zero for
this CFD symbol, so tick volume is the only available measure. It counts price
updates, so it is an activity proxy, not traded volume.

These are descriptive magnitudes and states only. Nothing here returns a
direction, and volume is never a standalone signal. Every value at bar i uses
bars 0..i only (no lookahead), so it can be read at the moment bar i closes.
"""
from typing import Dict, Iterable

import numpy as np
import pandas as pd

BASELINE_BARS = 20  # prior bars forming the recent-average baseline
PERCENTILE_WINDOW = 100
EXPANSION_RATIO = 1.5  # relative volume at or above this is labelled EXPANSION
CONTRACTION_RATIO = 0.67  # at or below this is labelled CONTRACTION


def relative_volume(volume: pd.Series, baseline: int = BASELINE_BARS) -> pd.Series:
    """Volume divided by the mean of the PRIOR `baseline` bars (bar itself excluded)."""
    prior_mean = volume.shift(1).rolling(baseline, min_periods=baseline).mean()
    return volume / prior_mean.where(prior_mean > 0)


def volume_percentile(volume: pd.Series, window: int = PERCENTILE_WINDOW) -> pd.Series:
    """Percentile (0-100) of each bar's volume within its trailing window, inclusive."""
    return volume.rolling(window, min_periods=window).apply(
        lambda w: 100.0 * np.sum(w <= w[-1]) / len(w), raw=True)


def volume_state(rel: float) -> str:
    if rel != rel:  # NaN: not enough history, unknown rather than normal
        return "UNKNOWN"
    if rel >= EXPANSION_RATIO:
        return "EXPANSION"
    if rel <= CONTRACTION_RATIO:
        return "CONTRACTION"
    return "NORMAL"


def volume_at(m5: pd.DataFrame, indices: Iterable[int]) -> Dict[int, dict]:
    """Volume descriptors for chosen bars (e.g. displacement, breakout, rejection).

    Each entry holds the bar's relative volume and percentile, a state label, and
    the mean relative volume over the bar and the two bars before it. Those three
    bars are all closed at the time bar i closes, so the result is safe to use live.
    """
    volume = m5["volume"].astype(float)
    rel = relative_volume(volume)
    pct = volume_percentile(volume)
    n = len(m5)
    out: Dict[int, dict] = {}
    for i in indices:
        if i < 0 or i >= n:
            continue
        r = float(rel.iloc[i])
        window = rel.iloc[max(0, i - 2): i + 1]
        p = float(pct.iloc[i])
        out[i] = {
            "relative_volume": r,
            "volume_percentile": p,
            "state": volume_state(r),
            "mean_relative_3bar": float(window.mean()) if window.notna().any() else float("nan"),
        }
    return out
