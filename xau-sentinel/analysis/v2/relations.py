"""Price relationship to a key area, plus the breakout/rejection events around it.

Relation priority, applied in this order:
    BROKEN       a closed bar crossed the area beyond the break buffer, and
                 price is still on that far side
    INSIDE       current price is within the area
    REJECTING    a closed bar in the last few bars was turned away from the area
                 and price is still on the rejected side
    APPROACHING  price is outside the area, within NEAR_ATR of its nearest edge
    ABOVE/BELOW  price is outside the area and further away than NEAR_ATR

ABOVE is added alongside the requested BELOW so both sides of an area are named.
Everything uses closed bars. A missing price or ATR gives UNKNOWN, never a guess.
"""
import math
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

import pandas as pd

from analysis.v2.events import Event
from analysis.v2.models import KeyArea

NEAR_ATR = 1.0  # outside the area, within this many ATR of an edge
BREAK_BUFFER_ATR = 0.1  # a close must clear the edge by this much to count as a break
RECENT_BARS = 24  # closed M5 bars scanned for breaks (about two hours)
REJECTION_BARS = 6  # bars after a break or rejection that still count as recent
RETEST_TOUCH_ATR = 0.5  # a retest must reach within this many ATR of the broken edge
# Kinds that describe a current state at an area. A later event of the opposite direction on the same
# area supersedes an earlier one (see _mark_superseded).
STATE_KINDS = ("BREAKOUT", "FAILED_BREAKOUT", "RETEST", "REJECTION")


def _retest_text(touched: bool, edge: float, closed_side: str) -> str:
    """'returned to X' only when the bar actually reached X. A retest that stopped short, but
    inside the RETEST_TOUCH_ATR tolerance, is described as a near-touch, never as reaching the edge."""
    reach = f"returned to {edge:.2f}" if touched else f"touched within {RETEST_TOUCH_ATR:g} ATR of {edge:.2f}"
    return f"{reach} and closed {closed_side} it"


def _mark_superseded(events: List[Event]) -> List[Event]:
    """Flags, without deleting, every state event that a LATER opposite-direction state event on the
    same area replaced. Example: RETEST bullish followed by FAILED_BREAKOUT bearish marks the RETEST
    superseded. Same-direction events never supersede each other."""
    out: List[Event] = []
    for e in events:
        stale = e.kind in STATE_KINDS and e.direction is not None and any(
            o.kind in STATE_KINDS and o.direction is not None and o.direction != e.direction and o.time > e.time
            for o in events)
        out.append(replace(e, superseded=True) if stale else e)
    return out

@dataclass(frozen=True)
class AreaState:
    area: KeyArea
    relation: str  # BROKEN | INSIDE | REJECTING | APPROACHING | ABOVE | BELOW | UNKNOWN
    distance_atr: Optional[float]  # 0 inside; positive when the area is above price
    reasons: Tuple[str, ...]
    events: Tuple[Event, ...] = field(default_factory=tuple)


def _unknown(area: KeyArea, reason: str) -> AreaState:
    return AreaState(area, "UNKNOWN", None, (reason,))


def classify_area(area: KeyArea, m5: Optional[pd.DataFrame], price: Optional[float],
                  atr: Optional[float]) -> AreaState:
    """Relation of `price` to `area`, plus its break, rejection and retest events
    over the last RECENT_BARS closed M5 bars. `m5` must hold closed bars only."""
    if price is None or atr is None or not atr > 0 or math.isnan(atr):
        return _unknown(area, "No usable current price or ATR.")
    if m5 is None or len(m5) < 3:
        return _unknown(area, "Not enough closed M5 bars.")

    win = m5.tail(RECENT_BARS + 1).reset_index(drop=True)
    buf = BREAK_BUFFER_ATR * atr
    times = list(win["time"])
    opens = win["open"].astype(float).tolist()
    highs = win["high"].astype(float).tolist()
    lows = win["low"].astype(float).tolist()
    closes = win["close"].astype(float).tolist()
    n = len(win)

    events: List[Event] = []

    def ev(kind, i, direction, detail):
        events.append(Event(kind, "M5", pd.Timestamp(times[i]), direction, area.mid, detail))

    up_breaks, down_breaks = [], []
    for i in range(1, n):
        if closes[i] > area.high + buf and closes[i - 1] <= area.high + buf:
            up_breaks.append(i)
            ev("BREAKOUT", i, "bullish", f"M5 close above {area.high:.2f} by the break buffer")
        if closes[i] < area.low - buf and closes[i - 1] >= area.low - buf:
            down_breaks.append(i)
            ev("BREAKOUT", i, "bearish", f"M5 close below {area.low:.2f} by the break buffer")

    rejection_idx = None
    rejection_side = None
    for i in range(max(1, n - REJECTION_BARS), n):
        if opens[i] < area.low and highs[i] >= area.low and closes[i] < area.low:
            rejection_idx, rejection_side = i, "bearish"
            ev("REJECTION", i, "bearish", f"wick into {area.low:.2f} from below, closed back below")
        elif opens[i] > area.high and lows[i] <= area.high and closes[i] > area.high:
            rejection_idx, rejection_side = i, "bullish"
            ev("REJECTION", i, "bullish", f"wick into {area.high:.2f} from above, closed back above")

    for i in up_breaks:
        back = [j for j in range(i + 1, min(n, i + 1 + REJECTION_BARS)) if closes[j] <= area.high]
        if back:
            ev("FAILED_BREAKOUT", back[0], "bearish", f"closed back below {area.high:.2f} after breaking above")
        retest = [j for j in range(i + 1, n) if lows[j] <= area.high + RETEST_TOUCH_ATR * atr and closes[j] > area.high]
        if retest:
            j = retest[-1]
            ev("RETEST", j, "bullish", _retest_text(lows[j] <= area.high, area.high, "above"))
    for i in down_breaks:
        back = [j for j in range(i + 1, min(n, i + 1 + REJECTION_BARS)) if closes[j] >= area.low]
        if back:
            ev("FAILED_BREAKOUT", back[0], "bullish", f"closed back above {area.low:.2f} after breaking below")
        retest = [j for j in range(i + 1, n) if highs[j] >= area.low - RETEST_TOUCH_ATR * atr and closes[j] < area.low]
        if retest:
            j = retest[-1]
            ev("RETEST", j, "bearish", _retest_text(highs[j] >= area.low, area.low, "below"))

    events.sort(key=lambda e: (e.time, e.kind))
    events = _mark_superseded(events)
    reasons: List[str] = []
    inside = area.low <= price <= area.high
    last_up = up_breaks[-1] if up_breaks else None
    last_down = down_breaks[-1] if down_breaks else None

    # The break counts only while price is still on the far side of the area.
    broke_up = last_up is not None and price > area.high
    broke_down = last_down is not None and price < area.low
    if broke_up and (last_down is None or last_up > last_down):
        relation = "BROKEN"
        reasons.append(f"M5 closed above {area.high:.2f}; price still above the area (broken upward).")
    elif broke_down and (last_up is None or last_down > last_up):
        relation = "BROKEN"
        reasons.append(f"M5 closed below {area.low:.2f}; price still below the area (broken downward).")
    elif inside:
        relation = "INSIDE"
        reasons.append(f"Price {price:.2f} is inside {area.low:.2f}-{area.high:.2f}.")
    elif rejection_idx is not None and (
        (rejection_side == "bearish" and price < area.low) or (rejection_side == "bullish" and price > area.high)
    ):
        relation = "REJECTING"
        reasons.append(f"Recent {rejection_side} rejection of the area; price has not returned through it.")
    else:
        if price < area.low:
            gap = (area.low - price) / atr
            outside_side = "BELOW"
        else:
            gap = (price - area.high) / atr
            outside_side = "ABOVE"
        if gap <= NEAR_ATR:
            relation = "APPROACHING"
            reasons.append(f"Price is {gap:.2f} ATR from the nearest edge of the area.")
        else:
            relation = outside_side
            reasons.append(f"Price is {gap:.2f} ATR {outside_side.lower()} the area.")

    if price < area.low:
        distance = (area.low - price) / atr
    elif price > area.high:
        distance = -(price - area.high) / atr
    else:
        distance = 0.0
    return AreaState(area, relation, round(distance, 4), tuple(reasons), tuple(events))
