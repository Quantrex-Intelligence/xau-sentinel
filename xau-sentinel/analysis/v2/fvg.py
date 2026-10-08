"""Fair value gaps: three-candle price imbalances, with retest and fill status.

    Bullish gap at bar i:  low[i] > high[i-2]   gap = [high[i-2], low[i]]
    Bearish gap at bar i:  high[i] < low[i-2]   gap = [high[i], low[i-2]]

Closed bars only. Detection at bar i uses bars i-2..i. Status after the gap forms uses
only later closed bars, so nothing looks ahead. A gap is OPEN until a later bar's range
enters it (RETESTED); it is FILLED once a later bar closes through the far side.

A gap is descriptive evidence about the market's recent imbalance. It is not a signal
to trade it. Only gaps formed inside FVG_LOOKBACK_BARS are reported.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from analysis.structure import compute_atr
from analysis.v2.heuristics import FVG_LOOKBACK_BARS

OPEN, RETESTED, FILLED = "OPEN", "RETESTED", "FILLED"


@dataclass(frozen=True)
class FairValueGap:
    direction: str  # bullish | bearish
    formed_at: pd.Timestamp  # open time of the third bar, the bar that completed the gap
    low: float
    high: float
    status: str  # OPEN | RETESTED | FILLED, as of the latest closed bar
    retested_at: Optional[pd.Timestamp]
    filled_at: Optional[pd.Timestamp]
    age_bars: int  # closed bars since the gap formed, measured to the latest closed bar
    size_atr: Optional[float]  # gap width in ATR at formation, when ATR is measurable

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


def find_fvgs(m5: Optional[pd.DataFrame], lookback: int = int(FVG_LOOKBACK_BARS.value)) -> Tuple[FairValueGap, ...]:
    """Fair value gaps formed in the last `lookback` closed bars, oldest first."""
    if m5 is None or len(m5) < 3:
        return ()
    df = m5.reset_index(drop=True)
    high, low = df["high"].astype(float).tolist(), df["low"].astype(float).tolist()
    time = df["time"].tolist()
    atr = compute_atr(df)
    n = len(df)
    first = max(2, n - lookback)

    gaps: List[FairValueGap] = []
    for i in range(first, n):
        atr_i = atr.iloc[i]
        if low[i] > high[i - 2]:
            gap_low, gap_high, direction = high[i - 2], low[i], "bullish"
        elif high[i] < low[i - 2]:
            gap_low, gap_high, direction = high[i], low[i - 2], "bearish"
        else:
            continue
        # Reset for every gap: a NaN ATR must not carry the previous gap's size forward.
        size_atr = None
        if pd.notna(atr_i) and atr_i > 0:
            size_atr = round((gap_high - gap_low) / float(atr_i), 4)
        gaps.append(_track(direction, time[i], gap_low, gap_high, size_atr, i, high, low, df, n))
    return tuple(gaps)


def _track(direction, formed, gap_low, gap_high, size_atr, i, high, low, df, n) -> FairValueGap:
    """Walks the closed bars after the gap formed and records the first retest and first fill."""
    retested_at = filled_at = None
    closes = df["close"].astype(float).tolist()
    for j in range(i + 1, n):
        if direction == "bullish":
            if retested_at is None and low[j] <= gap_high:
                retested_at = pd.Timestamp(df["time"].iloc[j])
            if closes[j] < gap_low:
                filled_at = pd.Timestamp(df["time"].iloc[j])
                break
        else:
            if retested_at is None and high[j] >= gap_low:
                retested_at = pd.Timestamp(df["time"].iloc[j])
            if closes[j] > gap_high:
                filled_at = pd.Timestamp(df["time"].iloc[j])
                break
    if filled_at is not None:
        status = FILLED
    elif retested_at is not None:
        status = RETESTED
    else:
        status = OPEN
    return FairValueGap(
        direction=direction, formed_at=pd.Timestamp(formed), low=float(gap_low), high=float(gap_high),
        status=status, retested_at=retested_at, filled_at=filled_at,
        age_bars=(n - 1) - i, size_atr=size_atr,
    )
