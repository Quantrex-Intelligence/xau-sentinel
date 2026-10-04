"""ATR-normalized measures. Pure functions over CLOSED candles only.

All distances are expressed as multiples of ATR so they are comparable across
price levels and volatility regimes. Inputs that cannot be measured return NaN;
callers must treat NaN as "unknown", never as zero.
"""
import math
from typing import Optional

import numpy as np
import pandas as pd

ATR_PERCENTILE_WINDOW = 100


def trailing_percentile(values, window: int) -> float:
    """Percentile (0-100) of the last value within the trailing window (inclusive)."""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < window:
        return float("nan")
    recent = arr[-window:]
    return float(100.0 * np.sum(recent <= recent[-1]) / len(recent))


def atr_normalized_distance(level: Optional[float], price: float, atr: float) -> float:
    """Signed distance (level - price) / ATR. Positive means the level is above price."""
    if level is None or atr is None or not atr > 0 or any(math.isnan(x) for x in (level, price, atr)):
        return float("nan")
    return (level - price) / atr


def zone_width_atr(low: float, high: float, atr: float) -> float:
    if atr is None or not atr > 0 or any(math.isnan(x) for x in (low, high, atr)):
        return float("nan")
    return (high - low) / atr


def swing_size_atr(swing_high: float, swing_low: float, atr: float) -> float:
    return zone_width_atr(swing_low, swing_high, atr)


def atr_percentile(atr_series: pd.Series, window: int = ATR_PERCENTILE_WINDOW) -> float:
    """Percentile (0-100) of the latest ATR within the trailing window, using only
    values up to and including the last row. NaN when history is too short."""
    return trailing_percentile(atr_series.to_numpy(dtype=float), window)


def range_ratio(bar_high: float, bar_low: float, recent_ranges: pd.Series) -> float:
    """Current bar range divided by the mean of the recent ranges (closed bars only)."""
    recent = recent_ranges.dropna()
    if recent.empty or recent.mean() <= 0:
        return float("nan")
    return float((bar_high - bar_low) / recent.mean())

