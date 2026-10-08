"""R-based, leakage-safe outcomes for research.

Hypothetical risk unit: R = 1 ATR(14) on M5, read at the observation bar.
Entry is the close of the observation bar. The stop is 1R against the trade and
targets are +1R, +2R, +3R. Scanning uses only bars after the observation bar,
within a fixed horizon. If one bar reaches both the stop and a target, the
stop is assumed first (conservative). Timeouts score 0 in expectancy and are
excluded from win rates.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

KS = (1, 2, 3)
HORIZON = 48
COST_R = 0.10  # round-trip cost sensitivity, in R (= ATR) units


@dataclass
class ROutcome:
    direction: str
    hit: Dict[int, bool] = field(default_factory=dict)
    stop_first: bool = False
    time_to_k: Dict[int, Optional[int]] = field(default_factory=dict)
    time_to_stop: Optional[int] = None
    mfe_r: float = 0.0
    mae_r: float = 0.0
    fwd_ret_48_atr: float = float("nan")  # signed by direction

    def expectancy(self, k: int) -> float:
        if self.hit[k]:
            return float(k)
        if self.stop_first:
            return -1.0
        return 0.0

    def outcome(self, k: int) -> str:
        if self.hit[k]:
            return "win"
        if self.stop_first:
            return "loss"
        return "timeout"


def r_outcome(m5: pd.DataFrame, i: int, direction: str, atr: float, horizon: int = HORIZON) -> Optional[ROutcome]:
    """m5 needs high/low/close columns, oldest first. Returns None if the bar has no ATR."""
    if direction not in ("BUY", "SELL"):
        raise ValueError(f"direction must be BUY or SELL, got {direction!r}")
    if atr is None or not atr > 0 or pd.isna(atr):
        return None
    n = len(m5)
    close = float(m5["close"].iloc[i])
    buy = direction == "BUY"
    out = ROutcome(direction=direction, hit={k: False for k in KS},
                   time_to_k={k: None for k in KS})
    end = min(i + horizon, n - 1)
    if end <= i:
        return out

    highs = m5["high"].values
    lows = m5["low"].values
    fav_max = 0.0
    adv_max = 0.0
    tgt_bar: Dict[int, Optional[int]] = {k: None for k in KS}
    stop_bar: Optional[int] = None
    for j in range(i + 1, end + 1):
        if buy:
            fav = (float(highs[j]) - close) / atr
            adv = (close - float(lows[j])) / atr
        else:
            fav = (close - float(lows[j])) / atr
            adv = (float(highs[j]) - close) / atr
        fav_max = max(fav_max, fav)
        adv_max = max(adv_max, adv)
        if stop_bar is None and adv >= 1.0:
            stop_bar = j
        for k in KS:
            if tgt_bar[k] is None and fav >= k:
                tgt_bar[k] = j

    out.mfe_r = round(fav_max, 6)
    out.mae_r = round(adv_max, 6)
    out.time_to_stop = (stop_bar - i) if stop_bar is not None else None
    out.stop_first = stop_bar is not None
    for k in KS:
        tb = tgt_bar[k]
        # Tie on the same bar goes to the stop, hence strict "<".
        hit = tb is not None and (stop_bar is None or tb < stop_bar)
        out.hit[k] = hit
        out.time_to_k[k] = (tb - i) if hit else None
    if i + horizon < n:
        fwd = (float(m5["close"].iloc[i + horizon]) - close) / atr
        out.fwd_ret_48_atr = fwd if buy else -fwd
    return out


def wilson(wins: int, decided: int, z: float = 1.96) -> Tuple[float, float]:
    from math import sqrt
    if decided == 0:
        return (float("nan"), float("nan"))
    p = wins / decided
    denom = 1 + z * z / decided
    centre = (p + z * z / (2 * decided)) / denom
    half = z * sqrt(p * (1 - p) / decided + z * z / (4 * decided * decided)) / denom
    return (centre - half, centre + half)
