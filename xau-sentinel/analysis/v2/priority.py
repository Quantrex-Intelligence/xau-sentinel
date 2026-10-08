"""Deterministic event priority and key-area relevance for Analysis Engine V2.

This decides what the ACTIVE views show. It never removes evidence: the engine keeps every
event it considered, and every key area stays on the analysis (only the active views are reduced).

Event tiers, highest first:
    1  structure and liquidity: SWEEP, MSS, BOS, DISPLACEMENT
    2  nearby area relations: BREAKOUT, RETEST, FAILED_BREAKOUT, REJECTION, kept only when the area
       is within ACTIVE_AREA_ATR of price
    3  volatility and range, and any other kind not listed above
    4  FVG, kept only when OPEN or RETESTED (FILLED gaps are dropped at the source) and within
       ACTIVE_AREA_ATR of price

Within a tier the order is most recent first, then nearest to price. Each tier keeps at most
TIER_CAPS[tier] events. Superseded events are not candidates at all.

The distance rule and the caps are deterministic settings. They are reported, not tuned.
"""
from typing import Dict, List, Optional, Sequence, Tuple

from analysis.v2.events import AREA_EVENT_KINDS, Event, sort_events
from analysis.v2.relations import AreaState

ACTIVE_AREA_ATR = 3.0  # a key area or area event is active only within this many ATR of price

TIER_STRUCTURE, TIER_AREA, TIER_OTHER, TIER_FVG = 1, 2, 3, 4
TIER_KINDS = {"SWEEP": TIER_STRUCTURE, "MSS": TIER_STRUCTURE, "BOS": TIER_STRUCTURE,
              "DISPLACEMENT": TIER_STRUCTURE, "FVG": TIER_FVG}
TIER_CAPS: Dict[int, int] = {TIER_STRUCTURE: 16, TIER_AREA: 12, TIER_OTHER: 6, TIER_FVG: 4}


def event_tier(e: Event) -> int:
    if e.kind in TIER_KINDS:
        return TIER_KINDS[e.kind]
    if e.kind in AREA_EVENT_KINDS:
        return TIER_AREA
    return TIER_OTHER


def is_active_area(a: AreaState) -> bool:
    """A key area is active when its distance to price is known and within ACTIVE_AREA_ATR. An
    area that contains price has distance 0 and is always active."""
    return a.distance_atr is not None and abs(a.distance_atr) <= ACTIVE_AREA_ATR


def active_areas(areas: Sequence[AreaState]) -> Tuple[AreaState, ...]:
    return tuple(a for a in areas if is_active_area(a))


def _distance_atr(e: Event, price: Optional[float], atr: Optional[float]) -> float:
    if price is None or atr is None or not atr > 0 or e.price is None:
        return float("inf")
    return abs(float(e.price) - price) / atr


def _is_relevant(e: Event, tier: int, price: Optional[float], atr: Optional[float]) -> bool:
    if tier in (TIER_AREA, TIER_FVG):
        return _distance_atr(e, price, atr) <= ACTIVE_AREA_ATR
    return True


def prioritize_events(events: Sequence[Event], price: Optional[float], atr: Optional[float]) -> Tuple[Event, ...]:
    """The bounded active stream: superseded events removed, relevance applied per tier, each tier
    capped, and the survivors returned in time order. Input order does not matter."""
    by_tier: Dict[int, List[Event]] = {}
    for e in events:
        if e.superseded:
            continue
        tier = event_tier(e)
        if not _is_relevant(e, tier, price, atr):
            continue
        by_tier.setdefault(tier, []).append(e)

    kept: List[Event] = []
    for tier in sorted(by_tier):
        ranked = sorted(by_tier[tier], key=lambda e: (-e.time.value, _distance_atr(e, price, atr), e.kind,
                                                      e.direction or "", float(e.price or 0.0)))
        kept.extend(ranked[: TIER_CAPS[tier]])
    return tuple(sort_events(kept))
