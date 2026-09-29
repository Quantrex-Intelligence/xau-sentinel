"""Liquidity sweep and equal-highs/lows detection.

A "sweep" requires price to trade beyond an identified level by at least a
configurable buffer and then close back on the other side — not just any
wick that grazes a level. This keeps noise out of the event feed.
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

import config
from analysis.structure import find_swing_points
from analysis.zones import _session_mask

SWEEPABLE_HIGH_LEVELS = ["Previous Day High", "Asian High", "London High", "H1 Swing High", "H4 Swing High"]
SWEEPABLE_LOW_LEVELS = ["Previous Day Low", "Asian Low", "London Low", "H1 Swing Low", "H4 Swing Low"]


@dataclass
class LiquidityEvent:
    time: pd.Timestamp
    label: str  # e.g. "Previous Day Low swept"
    level_name: str
    level_price: float
    kind: str  # "sweep_high", "sweep_low", "equal_high", "equal_low"


# Session levels are still being formed while the session runs, so a bar
# inside the session is tested against the session's extreme from bars
# strictly BEFORE it — never a level that already includes the bar under test
# or later bars (Stage 23A, VAL-014). name -> (session start, end, side).
_SESSION_LEVELS = {
    "Asian High": ("ASIAN_SESSION_START_UTC", "ASIAN_SESSION_END_UTC", "high"),
    "Asian Low": ("ASIAN_SESSION_START_UTC", "ASIAN_SESSION_END_UTC", "low"),
    "London High": ("LONDON_SESSION_START_UTC", "LONDON_SESSION_END_UTC", "high"),
    "London Low": ("LONDON_SESSION_START_UTC", "LONDON_SESSION_END_UTC", "low"),
}


def _session_level_before(df: pd.DataFrame, level_name: str, bar_time) -> Optional[float]:
    start_attr, end_attr, side = _SESSION_LEVELS[level_name]
    times = df["time"]
    mask = (
        (times.dt.date == bar_time.date())
        & (times < bar_time)
        & _session_mask(times, getattr(config, start_attr), getattr(config, end_attr))
    )
    if not mask.any():
        return None
    return float(df.loc[mask, "high"].max()) if side == "high" else float(df.loc[mask, "low"].min())


def _level_for_bar(df: pd.DataFrame, zones: dict, level_name: str, bar_time) -> Optional[float]:
    if level_name in _SESSION_LEVELS:
        level = _session_level_before(df, level_name, bar_time)
        return round(level, 2) if level is not None else None
    return zones.get(level_name)


def detect_sweeps(df: pd.DataFrame, zones: dict, lookback_bars: int = 20, buffer: float = None) -> List[LiquidityEvent]:
    """`df` is the full CLOSED M5 history (session levels are rebuilt from it
    bar by bar); only its last `lookback_bars` are tested for sweeps."""
    buffer = buffer if buffer is not None else config.LIQUIDITY_SWEEP_BUFFER_PIPS
    if df is None or df.empty:
        return []

    recent = df.tail(lookback_bars).reset_index(drop=True)
    events: List[LiquidityEvent] = []

    # Only the first qualifying bar per level counts as "the" sweep — once price
    # has traded through and closed back, later bars doing the same thing are
    # continuation, not a fresh liquidity event.
    for level_name in SWEEPABLE_HIGH_LEVELS:
        if zones.get(level_name) is None:
            continue
        for _, bar in recent.iterrows():
            price = _level_for_bar(df, zones, level_name, bar["time"])
            if price is not None and bar["high"] >= price + buffer and bar["close"] < price:
                events.append(LiquidityEvent(bar["time"], f"{level_name} swept", level_name, price, "sweep_high"))
                break

    for level_name in SWEEPABLE_LOW_LEVELS:
        if zones.get(level_name) is None:
            continue
        for _, bar in recent.iterrows():
            price = _level_for_bar(df, zones, level_name, bar["time"])
            if price is not None and bar["low"] <= price - buffer and bar["close"] > price:
                events.append(LiquidityEvent(bar["time"], f"{level_name} swept", level_name, price, "sweep_low"))
                break

    events.sort(key=lambda e: e.time)
    return _merge_coincident_sweeps(events)


def _merge_coincident_sweeps(events: List[LiquidityEvent]) -> List[LiquidityEvent]:
    """Two named levels at the same price (e.g. Asian Low == H1 Swing Low)
    swept by the same bar are ONE liquidity event, not two. The merged event
    keeps the first name in SWEEPABLE_*_LEVELS order as `level_name` (a fixed,
    deterministic choice) and lists every level in its label (Stage 23A,
    VAL-026). Input must already be time-sorted; the sort is stable, so
    order within one bar follows the level lists."""
    merged: List[LiquidityEvent] = []
    for e in events:
        prev = next((m for m in merged if m.time == e.time and m.kind == e.kind
                     and m.level_price == e.level_price), None)
        if prev is None:
            merged.append(LiquidityEvent(e.time, e.label, e.level_name, e.level_price, e.kind))
        else:
            names = prev.label[: -len(" swept")]
            prev.label = f"{names} + {e.level_name} swept"
    return merged


def detect_equal_levels(df: pd.DataFrame, tolerance: float = None, recent_n: int = 6) -> List[LiquidityEvent]:
    """Flags equal highs/lows among the most recent swing points — a liquidity
    pool, not a claim that every touch is significant."""
    tolerance = tolerance if tolerance is not None else config.EQUAL_LEVEL_TOLERANCE
    swings = find_swing_points(df)
    events: List[LiquidityEvent] = []

    # One event per swing point that equals any EARLIER one — a run of 3+
    # equal highs no longer emits the shared later points more than once
    # (Stage 23A, VAL-025).
    highs = [p for p in swings if p.kind == "high"][-recent_n:]
    for j in range(1, len(highs)):
        if any(abs(highs[i].price - highs[j].price) <= tolerance for i in range(j)):
            events.append(LiquidityEvent(highs[j].time, "Equal highs detected", "Equal Highs",
                                          highs[j].price, "equal_high"))

    lows = [p for p in swings if p.kind == "low"][-recent_n:]
    for j in range(1, len(lows)):
        if any(abs(lows[i].price - lows[j].price) <= tolerance for i in range(j)):
            events.append(LiquidityEvent(lows[j].time, "Equal lows detected", "Equal Lows",
                                          lows[j].price, "equal_low"))

    return events
