"""Layer 1 of Analysis Engine V2: raw observations.

Every input is a CLOSED candle. `closed_only()` drops the forming bar of each
timeframe before anything is measured, and the current price is the last
CLOSED M5 close, so no value here can depend on a bar that has not finished.

Missing or short history never raises. It is recorded in `data_issues` and the
affected fields are None or a state of "INSUFFICIENT", so every consumer can
tell "unknown" apart from "zero".
"""
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

import pandas as pd

import config
from analysis.liquidity import LiquidityEvent, detect_equal_levels, detect_sweeps
from analysis.structure import analyze_structure, closed_only, compute_atr, displacement_at
from analysis.v2.adx import latest_adx
from analysis.v2.normalize import atr_normalized_distance, atr_percentile, range_ratio
from analysis.v2.volume import volume_at
from analysis.zones import compute_zones, current_session

TIMEFRAMES = ("M5", "M15", "H1", "H4")
# Minimum CLOSED bars per timeframe before its structure is trusted. Structure
# needs a few swings on each side, and ATR and percentiles need a warm-up.
MIN_BARS = {"M5": 120, "M15": 60, "H1": 60, "H4": 40}
ATR_CHANGE_LOOKBACK = 10
RECENT_RANGE_BARS = 50  # window for the plain recent high/low used when swings are absent


@dataclass(frozen=True)
class TimeframeStructure:
    timeframe: str
    state: str  # BULLISH | BEARISH | RANGING | PULLBACK | INSUFFICIENT
    reason: str
    last_bos: Optional[str]
    last_mss: Optional[str]
    last_high: Optional[float]  # latest confirmed swing high
    last_low: Optional[float]  # latest confirmed swing low
    last_high_label: Optional[str]  # HH | LH
    last_low_label: Optional[str]  # HL | LL


@dataclass(frozen=True)
class Observations:
    as_of: Optional[datetime]
    current_price: Optional[float]
    session: Optional[str]
    structure: Dict[str, TimeframeStructure]
    atr_m5: Optional[float]
    atr_h1: Optional[float]
    atr_percentile_m5: Optional[float]
    atr_change_m5: Optional[float]  # ATR now / ATR `ATR_CHANGE_LOOKBACK` bars ago
    range_ratio_m5: Optional[float]  # last closed M5 range / mean of prior 20 ranges
    displacement_m5: Optional[str]  # bullish | bearish | None, last closed M5 bar
    volume_m5: dict  # relative_volume, volume_percentile, state of the last closed M5 bar
    zones: Dict[str, float]
    sweeps: Tuple[LiquidityEvent, ...]
    equal_levels: Tuple[LiquidityEvent, ...]
    data_issues: Tuple[str, ...] = field(default_factory=tuple)
    recent_high: Optional[float] = None  # highest high of the last RECENT_RANGE_BARS closed M5 bars
    recent_low: Optional[float] = None  # lowest low of the same window
    zone_distances_atr: Dict[str, float] = field(default_factory=dict)  # signed (level - price) / M5 ATR
    adx_h1: Optional[float] = None  # Wilder ADX(14) on closed H1 bars; trend strength only, no direction

    @property
    def ready(self) -> bool:
        return self.current_price is not None and self.atr_m5 is not None


def _num(value) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def _closed_frame(candles: dict, tf: str, issues: list) -> Optional[pd.DataFrame]:
    """Closed bars of one timeframe, or None (recorded in `issues`) when the
    frame is absent, lacks the closed flag, or is too short."""
    df = candles.get(tf)
    if df is None or len(df) == 0:
        issues.append(f"{tf}: no candles")
        return None
    if "is_closed" not in df.columns:
        issues.append(f"{tf}: no is_closed column, so closed candles cannot be enforced; frame ignored")
        return None
    closed = closed_only({tf: df})[tf]
    if len(closed) < MIN_BARS[tf]:
        issues.append(f"{tf}: insufficient closed history ({len(closed)} bars, need {MIN_BARS[tf]})")
        return None
    return closed


def _structure(tf: str, df: Optional[pd.DataFrame]) -> TimeframeStructure:
    if df is None:
        return TimeframeStructure(tf, "INSUFFICIENT", "No usable closed history.", None, None,
                                  None, None, None, None)
    result = analyze_structure(df)
    highs = [p for p in result.swings if p.kind == "high" and p.label]
    lows = [p for p in result.swings if p.kind == "low" and p.label]
    last_high = highs[-1] if highs else None
    last_low = lows[-1] if lows else None
    return TimeframeStructure(
        timeframe=tf, state=result.state, reason=result.reason,
        last_bos=result.last_bos, last_mss=result.last_mss,
        last_high=last_high.price if last_high else None,
        last_low=last_low.price if last_low else None,
        last_high_label=last_high.label if last_high else None,
        last_low_label=last_low.label if last_low else None,
    )


def build_observations(candles: dict) -> Observations:
    """Measure the market from CLOSED candles only. `candles` maps timeframe to
    a frame with [time, open, high, low, close, volume, close_time, is_closed]."""
    issues: list = []
    frames = {tf: _closed_frame(candles, tf, issues) for tf in TIMEFRAMES}
    m5, m15, h1, h4 = frames["M5"], frames["M15"], frames["H1"], frames["H4"]

    structure = {tf: _structure(tf, frames[tf]) for tf in TIMEFRAMES}

    if m5 is None:
        return Observations(None, None, None, structure, None, None, None, None, None, None,
                            {}, {}, (), (), tuple(issues))

    as_of = pd.Timestamp(m5["time"].iloc[-1]).to_pydatetime()
    current_price = _num(m5["close"].iloc[-1])
    session = current_session(as_of)

    atr_m5_series = compute_atr(m5)
    atr_m5 = _num(atr_m5_series.iloc[-1])
    atr_percentile_m5 = _num(atr_percentile(atr_m5_series))
    atr_change = None
    if len(atr_m5_series) > ATR_CHANGE_LOOKBACK:
        earlier = _num(atr_m5_series.iloc[-1 - ATR_CHANGE_LOOKBACK])
        if atr_m5 is not None and earlier:
            atr_change = atr_m5 / earlier

    ranges = (m5["high"] - m5["low"]).astype(float)
    range_ratio_m5 = _num(range_ratio(float(m5["high"].iloc[-1]), float(m5["low"].iloc[-1]),
                                      ranges.iloc[-21:-1]))

    atr_h1 = _num(compute_atr(h1).iloc[-1]) if h1 is not None else None

    displacement = displacement_at(m5, len(m5) - 1, atr=atr_m5_series)

    vol = volume_at(m5, [len(m5) - 1])[len(m5) - 1]

    recent = m5.tail(RECENT_RANGE_BARS)
    recent_high = _num(recent["high"].max())
    recent_low = _num(recent["low"].min())

    zones = compute_zones(m5, h1, h4)  # compute_zones accepts None for H1/H4
    sweeps = tuple(detect_sweeps(m5, zones))
    equal = tuple(detect_equal_levels(m5))

    return Observations(
        as_of=as_of, current_price=current_price, session=session, structure=structure,
        atr_m5=atr_m5, atr_h1=atr_h1, atr_percentile_m5=atr_percentile_m5, atr_change_m5=atr_change,
        range_ratio_m5=range_ratio_m5, displacement_m5=displacement, volume_m5=vol, zones=zones,
        sweeps=sweeps, equal_levels=equal, data_issues=tuple(issues),
        recent_high=recent_high, recent_low=recent_low,
        adx_h1=_num(latest_adx(h1)) if h1 is not None else None,
        zone_distances_atr={name: atr_normalized_distance(level, current_price, atr_m5)
                            for name, level in zones.items()} if current_price is not None else {},
    )
