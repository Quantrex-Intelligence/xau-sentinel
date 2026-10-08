"""Scoring: win rates with Wilson 95% intervals, base rate, non-overlapping
view, and breakdowns by month, direction, session, and regime.

Win rate is wins / (wins + losses). Timeouts are reported but excluded from
the rate, because a timeout is not a directional result.
"""
import math
from collections import Counter
from typing import Dict, Iterable, List

import pandas as pd

from backtest.outcome import label_signal
from backtest.replay import SIGNAL_TYPES, Signal


def wilson(wins: int, decided: int, z: float = 1.96):
    """Wilson score interval for a proportion. Well-behaved at small n and at
    proportions near 0 or 1, where the normal approximation is not."""
    if decided == 0:
        return (float("nan"), float("nan"))
    p = wins / decided
    denom = 1 + z * z / decided
    centre = (p + z * z / (2 * decided)) / denom
    half = z * math.sqrt(p * (1 - p) / decided + z * z / (4 * decided * decided)) / denom
    return (centre - half, centre + half)


def _rate(outcomes: Iterable[str]):
    c = Counter(outcomes)
    decided = c["win"] + c["loss"]
    return c["win"], decided, (c["win"] / decided if decided else float("nan"))


def non_overlapping(signals: List[Signal], horizon: int) -> List[Signal]:
    """Keep at most one signal per (type, direction) whose outcome window
    would otherwise overlap the previously kept one. A signal inside another
    signal's horizon describes the same price move, so counting both would
    overstate the sample."""
    kept: List[Signal] = []
    last: Dict[tuple, int] = {}
    for s in sorted(signals, key=lambda x: x.index):
        key = (s.signal_type, s.direction)
        if key in last and s.index < last[key] + horizon:
            continue
        kept.append(s)
        last[key] = s.index
    return kept


def base_rate(m5: pd.DataFrame, atr: pd.Series, indices: Iterable[int], horizon: int, k: float):
    """Win rate if every sampled bar were labeled in both directions. This is
    what an uninformed signal would score, so lift is measured against it."""
    outcomes = []
    for i in indices:
        if pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
            continue
        for direction in ("BUY", "SELL"):
            outcomes.append(label_signal(m5, i, direction, float(atr.iloc[i]), horizon, k).outcome)
    return _rate(outcomes)


def _row(group: str, signals: List[Signal], base: float) -> dict:
    wins, decided, wr = _rate(s.outcome for s in signals)
    lo, hi = wilson(wins, decided)
    return {
        "group": group,
        "n": len(signals),
        "decided": decided,
        "timeouts": sum(1 for s in signals if s.outcome == "timeout"),
        "win_rate": round(wr, 3) if decided else None,
        "ci95_low": round(lo, 3) if decided else None,
        "ci95_high": round(hi, 3) if decided else None,
        "lift_vs_base": round(wr - base, 3) if decided else None,
    }


def summarize(signals: List[Signal], base: float, horizon: int) -> pd.DataFrame:
    """One row per signal type, on the raw (overlapping) signals and on the
    non-overlapping subset, so the effect of overlap is visible."""
    rows = []
    for signal_type in SIGNAL_TYPES:
        mine = [s for s in signals if s.signal_type == signal_type]
        rows.append({**_row(f"{signal_type} (all)", mine, base)})
        rows.append({**_row(f"{signal_type} (non-overlap)", non_overlapping(mine, horizon), base)})
    return pd.DataFrame(rows)


def non_overlap_row(signals: List[Signal], base: float, horizon: int, signal_type: str) -> dict:
    """The non-overlapping row for ONE signal type, computed directly. Use this
    rather than selecting a row out of summarize() by name: summarize() returns
    every type's rows, and a name match picks up the wrong type's empty row."""
    mine = [s for s in signals if s.signal_type == signal_type]
    return _row(f"{signal_type} (non-overlap)", non_overlapping(mine, horizon), base)


def breakdown(signals: List[Signal], base: float, field: str) -> pd.DataFrame:
    rows = []
    keys = sorted({getattr(s, field) if field != "month" else s.time.strftime("%Y-%m") for s in signals})
    for key in keys:
        grp = [s for s in signals if (s.time.strftime("%Y-%m") if field == "month" else getattr(s, field)) == key]
        rows.append(_row(str(key), grp, base))
    return pd.DataFrame(rows)
