"""Liquidity sweep and equal-highs/lows detection.

A "sweep" requires price to trade beyond an identified level by at least a
configurable buffer and then close back on the other side — not just any
wick that grazes a level. This keeps noise out of the event feed.
"""
from dataclasses import dataclass
from typing import List

import pandas as pd

import config
from analysis.structure import find_swing_points

SWEEPABLE_HIGH_LEVELS = ["Previous Day High", "Asian High", "London High", "H1 Swing High", "H4 Swing High"]
SWEEPABLE_LOW_LEVELS = ["Previous Day Low", "Asian Low", "London Low", "H1 Swing Low", "H4 Swing Low"]


@dataclass
class LiquidityEvent:
    time: pd.Timestamp
    label: str  # e.g. "Previous Day Low swept"
    level_name: str
    level_price: float
    kind: str  # "sweep_high", "sweep_low", "equal_high", "equal_low"


def detect_sweeps(df: pd.DataFrame, zones: dict, lookback_bars: int = 20, buffer: float = None) -> List[LiquidityEvent]:
    buffer = buffer if buffer is not None else config.LIQUIDITY_SWEEP_BUFFER_PIPS
    if df is None or df.empty:
        return []

    recent = df.tail(lookback_bars).reset_index(drop=True)
    events: List[LiquidityEvent] = []

    # Only the first qualifying bar per level counts as "the" sweep — once price
    # has traded through and closed back, later bars doing the same thing are
    # continuation, not a fresh liquidity event.
    for level_name in SWEEPABLE_HIGH_LEVELS:
        price = zones.get(level_name)
        if price is None:
            continue
        for _, bar in recent.iterrows():
            if bar["high"] >= price + buffer and bar["close"] < price:
                events.append(LiquidityEvent(bar["time"], f"{level_name} swept", level_name, price, "sweep_high"))
                break

    for level_name in SWEEPABLE_LOW_LEVELS:
        price = zones.get(level_name)
        if price is None:
            continue
        for _, bar in recent.iterrows():
            if bar["low"] <= price - buffer and bar["close"] > price:
                events.append(LiquidityEvent(bar["time"], f"{level_name} swept", level_name, price, "sweep_low"))
                break

    events.sort(key=lambda e: e.time)
    return events


def detect_equal_levels(df: pd.DataFrame, tolerance: float = None, recent_n: int = 6) -> List[LiquidityEvent]:
    """Flags equal highs/lows among the most recent swing points — a liquidity
    pool, not a claim that every touch is significant."""
    tolerance = tolerance if tolerance is not None else config.EQUAL_LEVEL_TOLERANCE
    swings = find_swing_points(df)
    events: List[LiquidityEvent] = []

    highs = [p for p in swings if p.kind == "high"][-recent_n:]
    for i in range(len(highs) - 1):
        for j in range(i + 1, len(highs)):
            if abs(highs[i].price - highs[j].price) <= tolerance:
                events.append(LiquidityEvent(highs[j].time, "Equal highs detected", "Equal Highs",
                                              highs[j].price, "equal_high"))

    lows = [p for p in swings if p.kind == "low"][-recent_n:]
    for i in range(len(lows) - 1):
        for j in range(i + 1, len(lows)):
            if abs(lows[i].price - lows[j].price) <= tolerance:
                events.append(LiquidityEvent(lows[j].time, "Equal lows detected", "Equal Lows",
                                              lows[j].price, "equal_low"))

    return events
