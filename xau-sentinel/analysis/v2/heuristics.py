"""Thresholds imported from the reference project's audit, isolated in one place.

Every value here is an UNVALIDATED HEURISTIC. Each entry records where it came from
and states that it has not been validated on XAU Sentinel's data. They are not proven
market edges and are not tuned here. They describe evidence; they never gate a trade.

Changing a value here changes only V2's descriptive evidence. It must not change
A+'s candidate sweep, its rules, or its rating.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Heuristic:
    value: float
    source: str  # where the number was taken from
    validated: bool  # always False for imported heuristics


_REF = "reference project signals/strategies"

# Wilder smoothing length. The standard textbook period, not a tuned value.
ADX_PERIOD = Heuristic(14, "Wilder (1978) convention", False)
# Trend-strength bands. The reference uses ADX 18 as a trend gate and 35 as a strong-trend veto.
ADX_WEAK_BELOW = Heuristic(18.0, f"{_REF}/ict_smc/detector.py ADX_TREND_MIN", False)
ADX_STRONG_AT_OR_ABOVE = Heuristic(35.0, f"{_REF}/sr_zone/detector.py ADX_RANGE_MAX", False)

# Pivot clustering into zones: pivots within this many ATRs of each other form one zone.
ZONE_ATR_FRACTION = Heuristic(0.5, f"{_REF}/sr_zone/detector.py ZONE_ATR_FRACTION", False)
# A zone counts as tested only after at least this many pivots.
ZONE_MIN_TOUCHES = Heuristic(2, f"{_REF}/sr_zone/detector.py MIN_TOUCHES", False)

# Fair value gap: how many closed bars back the gap detection and retest tracking look.
# This is an analysis-window choice made for XAU Sentinel, not a value from the reference.
FVG_LOOKBACK_BARS = Heuristic(30, "XAU Sentinel analysis window (not from the reference)", False)

PROVENANCE_NOTE = (
    "Imported heuristics. Not validated on XAU Sentinel data. Not optimized. "
    "Used only as descriptive V2 evidence."
)
