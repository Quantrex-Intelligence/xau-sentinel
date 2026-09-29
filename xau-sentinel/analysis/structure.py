"""Deterministic swing-based market structure engine.

Produces one of four states per timeframe: BULLISH, BEARISH, RANGING, PULLBACK.
This only labels price action that has already happened — it does not predict
the future and does not produce probability scores.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    # "The latest close is currently beyond the last confirmed swing that
    # defined the trend" — a state, NOT "a shift just happened": it has no
    # recency bound and can flip bar to bar. Consumers that need a shift tied
    # to a specific bar (the M5 entry sequence) use analysis/sequence.py
    # instead (Stage 23A, VAL-018).
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
        elif last_close > last_high.price:
            # BOS is measured against the latest confirmed HH, not the
            # superseded one before it (Stage 23A, VAL-013).
            last_bos = "bullish"
    elif bearish_struct:
        state = "BEARISH"
        reason = f"{last_high.label} + {last_low.label}: downtrend intact."
        if last_close > last_high.price:
            last_mss = "bullish"
            state = "PULLBACK"
            reason = "Price closed above the last lower-high — possible bullish shift developing."
        elif last_close < last_low.price:
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


def displacement_at(df: pd.DataFrame, i: int, atr_mult: float = None, atr: pd.Series = None) -> Optional[str]:
    """Returns 'bullish'/'bearish' if candle `i`'s body is an outsized,
    ATR-relative move, else None. Uses ATR through the *prior* candle
    (i - 1) so a candle is never measured against a baseline that includes
    itself (no look-ahead). `atr` may be passed in precomputed when scanning
    many bars."""
    atr_mult = atr_mult if atr_mult is not None else config.DISPLACEMENT_ATR_MULT
    if df is None or i < config.ATR_PERIOD + 1 or i >= len(df):
        return None

    atr = atr if atr is not None else compute_atr(df)
    reference_atr = float(atr.iloc[i - 1])
    if reference_atr <= 0:
        return None

    bar = df.iloc[i]
    body = float(bar["close"] - bar["open"])
    if body > reference_atr * atr_mult:
        return "bullish"
    if body < -reference_atr * atr_mult:
        return "bearish"
    return None


def detect_displacement(df: pd.DataFrame, atr_mult: float = None) -> Optional[str]:
    """Displacement on the most recent candle — see displacement_at()."""
    if df is None or len(df) < config.ATR_PERIOD + 2:
        return None
    return displacement_at(df, len(df) - 1, atr_mult)


def is_feed_stale(m5: pd.DataFrame, now: datetime, timeframe_minutes: int = 5) -> bool:
    """True when the newest M5 row (closed or still forming) opened longer
    ago than one bar + config.DATA_STALE_SECONDS — i.e. no new bar has
    arrived when one should have (frozen feed, MT5 outage, weekend). Reads
    the candles themselves, so it guards the analysis path directly rather
    than only the UI badge (Stage 23A, VAL-011)."""
    if m5 is None or m5.empty:
        return True
    latest = m5["time"].iloc[-1]
    if hasattr(latest, "to_pydatetime"):
        latest = latest.to_pydatetime()
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    age = (now - latest).total_seconds()
    return age > timeframe_minutes * 60 + config.DATA_STALE_SECONDS
