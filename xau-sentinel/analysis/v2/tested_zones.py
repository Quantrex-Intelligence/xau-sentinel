"""Touch-validated support and resistance zones.

A zone is built by clustering swing pivots of one kind whose prices lie within an
ATR-based width of each other. A zone counts only when it has been tested by at
least ZONE_MIN_TOUCHES pivots. Each zone keeps the times and prices of the pivots
that formed it, so its evidence can be audited.

Swing pivots come from the existing analysis.structure.find_swing_points, so this
module adds no new swing definition. Only closed bars are passed in.

The width fraction and the touch minimum are imported heuristics (heuristics.py).
Zones are descriptive evidence for key areas. They do not change A+.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from analysis.structure import find_swing_points
from analysis.v2.heuristics import ZONE_ATR_FRACTION, ZONE_MIN_TOUCHES


@dataclass(frozen=True)
class PivotTouch:
    time: pd.Timestamp  # open time of the closed bar that formed the pivot
    price: float


@dataclass(frozen=True)
class TestedZone:
    kind: str  # SUPPORT (from swing lows) | RESISTANCE (from swing highs)
    low: float
    high: float
    touches: Tuple[PivotTouch, ...]

    @property
    def touch_count(self) -> int:
        return len(self.touches)


def _cluster(pivots: List[PivotTouch], width: float) -> List[List[PivotTouch]]:
    """Grouping of sorted prices with a capped span. A price joins the running group only while
    it stays within `width` of the group's FIRST price. Plain single-linkage (chaining each price
    to the one before) let a run of nearby pivots stretch one zone across many ATRs; capping the
    span keeps every zone no wider than one cluster width. This is a deliberate deviation from
    the reference's chaining rule, made because the chained zones were not useful levels."""
    ordered = sorted(pivots, key=lambda p: p.price)
    groups: List[List[PivotTouch]] = []
    for p in ordered:
        if groups and p.price - groups[-1][0].price <= width:
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def build_tested_zones(h1: Optional[pd.DataFrame], atr_value: Optional[float]) -> Tuple[TestedZone, ...]:
    """Tested zones from closed H1 bars. Empty when the ATR is unusable or history is short."""
    if h1 is None or len(h1) < 10 or atr_value is None or not atr_value > 0:
        return ()
    width = ZONE_ATR_FRACTION.value * atr_value
    swings = find_swing_points(h1.reset_index(drop=True))

    zones: List[TestedZone] = []
    for kind, label in (("low", "SUPPORT"), ("high", "RESISTANCE")):
        pivots = [PivotTouch(pd.Timestamp(p.time), float(p.price)) for p in swings if p.kind == kind]
        for group in _cluster(pivots, width):
            if len(group) < ZONE_MIN_TOUCHES.value:
                continue
            zones.append(TestedZone(
                kind=label,
                low=min(p.price for p in group),
                high=max(p.price for p in group),
                touches=tuple(sorted(group, key=lambda p: p.time)),
            ))
    return tuple(sorted(zones, key=lambda z: (z.low, z.kind)))
