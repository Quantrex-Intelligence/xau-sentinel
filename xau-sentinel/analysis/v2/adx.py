"""Wilder Average Directional Index: trend strength, independent of direction.

Deterministic, closed-bar only. Each value at bar i uses bars 0..i, so nothing here
looks ahead. The first value appears after 2*period bars of history.

ADX is descriptive evidence about how strongly the market is trending. It says
nothing about which way, and it is not a trading signal.
"""
from typing import List, Optional

import pandas as pd

from analysis.v2.heuristics import ADX_PERIOD, ADX_STRONG_AT_OR_ABOVE, ADX_WEAK_BELOW


def adx_series(high: List[float], low: List[float], close: List[float],
               period: int = int(ADX_PERIOD.value)) -> List[Optional[float]]:
    """ADX aligned 1:1 with the inputs. None until enough history exists."""
    n = len(close)
    out: List[Optional[float]] = [None] * n
    if period <= 0 or n < 2 * period + 1:
        return out

    tr_sum = pdm_sum = mdm_sum = 0.0
    dx_values: List[float] = []
    adx_prev: Optional[float] = None
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        pdm = up if (up > down and up > 0) else 0.0
        mdm = down if (down > up and down > 0) else 0.0
        tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

        if i <= period:  # seed the smoothed sums with the first `period` bars
            tr_sum += tr
            pdm_sum += pdm
            mdm_sum += mdm
            if i < period:
                continue
        else:  # Wilder smoothing: keep (period-1)/period of the prior sum, add this bar
            tr_sum = tr_sum - tr_sum / period + tr
            pdm_sum = pdm_sum - pdm_sum / period + pdm
            mdm_sum = mdm_sum - mdm_sum / period + mdm

        if tr_sum <= 0:
            continue
        plus_di = 100.0 * pdm_sum / tr_sum
        minus_di = 100.0 * mdm_sum / tr_sum
        di_total = plus_di + minus_di
        dx = 0.0 if di_total == 0 else 100.0 * abs(plus_di - minus_di) / di_total

        if adx_prev is None:
            dx_values.append(dx)
            if len(dx_values) == period:
                adx_prev = sum(dx_values) / period
                out[i] = adx_prev
        else:
            adx_prev = (adx_prev * (period - 1) + dx) / period
            out[i] = adx_prev
    return out


def latest_adx(df: pd.DataFrame, period: int = int(ADX_PERIOD.value)) -> Optional[float]:
    """Most recent ADX of a closed-bar frame, or None when history is too short."""
    if df is None or len(df) == 0:
        return None
    values = adx_series(df["high"].astype(float).tolist(), df["low"].astype(float).tolist(),
                        df["close"].astype(float).tolist(), period)
    return values[-1]


def trend_strength_state(adx_value: Optional[float]) -> str:
    """Descriptive band. The cut-offs are imported heuristics (see heuristics.py)."""
    if adx_value is None:
        return "UNKNOWN"
    if adx_value >= ADX_STRONG_AT_OR_ABOVE.value:
        return "STRONG_TREND"
    if adx_value < ADX_WEAK_BELOW.value:
        return "WEAK_TREND"
    return "DEVELOPING_TREND"
