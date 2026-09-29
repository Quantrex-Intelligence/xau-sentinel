"""Deterministic swing-based market structure engine.

Produces one of four states per timeframe: BULLISH, BEARISH, RANGING, PULLBACK.
This only labels price action that has already happened — it does not predict
the future and does not produce probability scores.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

import config


@dataclass
class SwingPoint:
    index: int
    time: pd.Timestamp
    price: float
    kind: str  # "high" or "low"
    label: Optional[str] = None  # "HH", "HL", "LH", "LL"


@dataclass
class StructureResult:
    state: str
    swings: List[SwingPoint] = field(default_factory=list)
    last_bos: Optional[str] = None  # "bullish" / "bearish" / None
    last_mss: Optional[str] = None  # "bullish" / "bearish" / None
    reason: str = ""


def closed_only(candles: dict) -> dict:
    """Filters each timeframe's candles down to CLOSED bars only, using
    the is_closed column mt5/market_data.py attaches (Stage 21, VAL-006 —
    see docs/validation/ISSUE_LOG.md). Structural analysis (swings,
    MSS/BOS, sweeps, displacement, retracement, zones) must never see a
    still-forming candle; an explicit "current price" read (entry
    planning, live display, charting) is exempt and reads the original,
    unfiltered dict directly instead of calling this."""
    return {tf: df[df["is_closed"]].reset_index(drop=True) for tf, df in candles.items()}


def find_swing_points(df: pd.DataFrame, lookback: int = None) -> List[SwingPoint]:
    """A bar is a swing high/low if it is the strict extreme within `lookback`
    bars on both sides. Simple and deterministic, no repainting once a bar's
    neighborhood has fully formed."""
    lookback = lookback or config.SWING_LOOKBACK
    points: List[SwingPoint] = []
    if df is None or len(df) < lookback * 2 + 1:
        return points

    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    for i in range(lookback, n - lookback):
        window_high = highs[i - lookback: i + lookback + 1]
        if highs[i] == window_high.max() and (window_high == highs[i]).sum() == 1:
            points.append(SwingPoint(i, df["time"].iloc[i], float(highs[i]), "high"))

        window_low = lows[i - lookback: i + lookback + 1]
        if lows[i] == window_low.min() and (window_low == lows[i]).sum() == 1:
            points.append(SwingPoint(i, df["time"].iloc[i], float(lows[i]), "low"))

    points.sort(key=lambda p: p.index)
    _label_swings(points)
    return points


def _label_swings(points: List[SwingPoint]) -> None:
    last_high: Optional[SwingPoint] = None
    last_low: Optional[SwingPoint] = None
    for p in points:
        if p.kind == "high":
            if last_high is not None:
                p.label = "HH" if p.price > last_high.price else "LH"
            last_high = p
        else:
            if last_low is not None:
                p.label = "HL" if p.price > last_low.price else "LL"
            last_low = p


def analyze_structure(df: pd.DataFrame, lookback: int = None) -> StructureResult:
    lookback = lookback or config.SWING_LOOKBACK
    if df is None or len(df) < lookback * 2 + 5:
        return StructureResult(state="RANGING", reason="Not enough candle history yet.")

    swings = find_swing_points(df, lookback)
    labeled = [p for p in swings if p.label is not None]
    if len(labeled) < 2:
        return StructureResult(state="RANGING", swings=swings, reason="No clear swing sequence yet.")

    recent_highs = [p for p in labeled if p.kind == "high"][-2:]
    recent_lows = [p for p in labeled if p.kind == "low"][-2:]
    last_close = float(df["close"].iloc[-1])

    last_high = recent_highs[-1] if recent_highs else None
    last_low = recent_lows[-1] if recent_lows else None
    prior_high = recent_highs[-2] if len(recent_highs) == 2 else None
    prior_low = recent_lows[-2] if len(recent_lows) == 2 else None

    bullish_struct = last_high is not None and last_high.label == "HH" and \
        last_low is not None and last_low.label == "HL"
    bearish_struct = last_high is not None and last_high.label == "LH" and \
        last_low is not None and last_low.label == "LL"

    last_bos = None
    last_mss = None

    if bullish_struct:
        state = "BULLISH"
        reason = f"{last_high.label} + {last_low.label}: uptrend intact."
        if last_close < last_low.price:
            last_mss = "bearish"
            state = "PULLBACK"
            reason = "Price closed below the last higher-low — possible bearish shift developing."
        elif prior_high and last_close > prior_high.price:
            last_bos = "bullish"
    elif bearish_struct:
        state = "BEARISH"
        reason = f"{last_high.label} + {last_low.label}: downtrend intact."
        if last_close > last_high.price:
            last_mss = "bullish"
            state = "PULLBACK"
            reason = "Price closed above the last lower-high — possible bullish shift developing."
        elif prior_low and last_close < prior_low.price:
            last_bos = "bearish"
    elif last_high and last_high.label == "HH" and last_low and last_low.label == "LL":
        state = "RANGING"
        reason = "Higher high but lower low — no clean directional structure."
    elif last_high and last_high.label == "LH" and last_low and last_low.label == "HL":
        state = "RANGING"
        reason = "Lower high but higher low — range compressing."
    else:
        state = "RANGING"
        reason = "No consistent HH/HL or LH/LL sequence yet."

    return StructureResult(state=state, swings=swings, last_bos=last_bos, last_mss=last_mss, reason=reason)


def compute_atr(df: pd.DataFrame, period: int = None) -> pd.Series:
    period = period or config.ATR_PERIOD
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.rolling(period, min_periods=1).mean()


def detect_displacement(df: pd.DataFrame, atr_mult: float = None) -> Optional[str]:
    """Returns 'bullish'/'bearish' if the most recent candle's body is an
    outsized, ATR-relative move, else None. Uses ATR through the *prior*
    candle so a candle is never measured against a baseline that includes
    itself (no look-ahead)."""
    atr_mult = atr_mult if atr_mult is not None else config.DISPLACEMENT_ATR_MULT
    if df is None or len(df) < config.ATR_PERIOD + 2:
        return None

    atr = compute_atr(df)
    last = df.iloc[-1]
    reference_atr = float(atr.iloc[-2])
    if reference_atr <= 0:
        return None

    body = float(last["close"] - last["open"])
    if body > reference_atr * atr_mult:
        return "bullish"
    if body < -reference_atr * atr_mult:
        return "bearish"
    return None
