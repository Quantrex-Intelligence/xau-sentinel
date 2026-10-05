"""Layer 7 of Analysis Engine V2: conditional scenarios.

A scenario says what WOULD have to happen, what would confirm it, and what
would invalidate it, using the structure levels and areas already measured.
These are conditions, not predictions and not trade instructions. None of them
carries a probability, and none tells anyone to enter, exit or size anything.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

from analysis.v2.confluence import Confluence
from analysis.v2.narrative import event_line
from analysis.v2.context import MarketContext
from analysis.v2.observations import Observations
from analysis.v2.relations import AreaState

RECENT_WINDOW = timedelta(minutes=30)  # events older than this are not cited as current
MAX_EVENT_REFS = 3

DISCLAIMER = ("Conditional scenarios describe what would need to happen. They are not predictions "
              "and not trade signals.")


@dataclass(frozen=True)
class Scenario:
    name: str  # CONTINUATION | REVERSAL | RANGE
    direction: Optional[str]  # bullish | bearish | None
    condition: str
    supporting_conditions: Tuple[str, ...]
    confirmation_requirements: Tuple[str, ...]
    invalidation_conditions: Tuple[str, ...]
    key_area_refs: Tuple[str, ...]
    event_refs: Tuple[str, ...]
    disclaimer: str = DISCLAIMER


def _nearest(areas: List[AreaState], price: float, above: bool) -> Optional[AreaState]:
    if above:
        candidates = [a for a in areas if a.area.low > price]
        return min(candidates, key=lambda a: a.area.low - price, default=None)
    candidates = [a for a in areas if a.area.high < price]
    return min(candidates, key=lambda a: price - a.area.high, default=None)


def _area_label(a: AreaState) -> str:
    return f"{a.area.low:.2f}-{a.area.high:.2f} ({a.relation})"


def _structure_line(obs: Observations) -> str:
    st = obs.structure
    return ("Structure: H4 {}, H1 {}, M15 {}, M5 {}; no clear trend on H1 or H4.".format(
        st["H4"].state.lower(), st["H1"].state.lower(), st["M15"].state.lower(), st["M5"].state.lower()))


def _sup(confluence: Confluence, direction: str) -> Tuple[str, ...]:
    return tuple(sorted({f"{l.source}: {l.detail}" for l in confluence.supporting if l.lean == direction}))


def build_scenarios(obs: Observations, context: MarketContext, confluence: Confluence,
                    areas: List[AreaState], events) -> Tuple[Scenario, ...]:
    price = obs.current_price
    if price is None:
        return ()
    h1, m5 = obs.structure["H1"], obs.structure["M5"]
    window_start = obs.as_of - RECENT_WINDOW if obs.as_of is not None else None
    recent = sorted((e for e in events if window_start is None or e.time >= window_start), key=lambda e: e.time)

    def refs(kinds):
        picked = [e for e in recent if e.kind in kinds][-MAX_EVENT_REFS:]
        return tuple(event_line(e) for e in picked)

    ref_kinds_continuation = {"BOS", "MSS", "SWEEP", "BREAKOUT", "RETEST", "FAILED_BREAKOUT"}
    ref_kinds_reversal = {"MSS", "SWEEP", "REJECTION", "FAILED_BREAKOUT", "DISPLACEMENT"}
    ref_kinds_range = {"COMPRESSION", "VOLATILITY_EXPANSION", "VOLATILITY_CONTRACTION", "SWEEP", "REJECTION", "RANGE_EXPANSION"}
    scenarios: List[Scenario] = []
    ref = confluence.reference

    if ref in ("bullish", "bearish"):
        up = ref == "bullish"
        target = _nearest(areas, price, above=up)
        name = "CONTINUATION"
        if up:
            level_text = (f"M5 closes above {h1.last_high:.2f} (latest H1 swing high), and the next closed M5 bar "
                          f"does not close back below it"
                          if h1.last_high is not None else "M5 closes above its latest swing high")
            invalid = [f"M5 closes below {h1.last_low:.2f} (latest H1 swing low)"
                       if h1.last_low is not None else "M5 closes below its latest swing low",
                       "H1 structure turns BEARISH"]
            condition = "Continuation needs M5 to close above the latest H1 swing high and hold above it."
        else:
            level_text = (f"M5 closes below {h1.last_low:.2f} (latest H1 swing low), and the next closed M5 bar "
                          f"does not close back above it"
                          if h1.last_low is not None else "M5 closes below its latest swing low")
            invalid = [f"M5 closes above {h1.last_high:.2f} (latest H1 swing high)"
                       if h1.last_high is not None else "M5 closes above its latest swing high",
                       "H1 structure turns BULLISH"]
            condition = "Continuation needs M5 to close below the latest H1 swing low and hold below it."
        scenarios.append(Scenario(
            name=name, direction=ref, condition=condition,
            supporting_conditions=_sup(confluence, ref),
            confirmation_requirements=(level_text,),
            invalidation_conditions=tuple(invalid),
            key_area_refs=(_area_label(target),) if target else (),
            event_refs=refs(ref_kinds_continuation),
        ))

        opposite = "bearish" if up else "bullish"
        m5_level = m5.last_low if up else m5.last_high
        m5_invalid = m5.last_high if up else m5.last_low
        if m5_level is not None and m5_invalid is not None:
            confirm = (f"M5 closes {'below' if up else 'above'} {m5_level:.2f} (latest M5 swing "
                       f"{'low' if up else 'high'}), a structure shift (MSS) against the {ref} trend, "
                       f"followed by a {opposite} displacement bar")
            scenarios.append(Scenario(
                name="REVERSAL", direction=opposite,
                condition=f"A reversal would start with a {opposite} structure shift on M5 against the {ref} trend.",
                supporting_conditions=_sup(confluence, opposite),
                confirmation_requirements=(confirm,),
                invalidation_conditions=(f"M5 closes {'above' if up else 'below'} {m5_invalid:.2f} "
                                         f"(latest M5 swing {'high' if up else 'low'}), which would undo the shift",),
                key_area_refs=tuple(_area_label(a) for a in areas if a.relation in ("REJECTING", "BROKEN"))[:2],
                event_refs=refs(ref_kinds_reversal),
            ))

    else:
        # Range edges: confirmed H1 swings, then M5 swings, then the plain recent
        # high/low, so a flat market still gets explicit edges to test against.
        rng_hi = next((x for x in (h1.last_high, m5.last_high, obs.recent_high) if x is not None), None)
        rng_lo = next((x for x in (h1.last_low, m5.last_low, obs.recent_low) if x is not None), None)
        if rng_hi is not None and rng_lo is not None and rng_hi > rng_lo:
            scenarios.append(Scenario(
                name="RANGE", direction=None,
                condition=f"While price stays within {rng_lo:.2f}-{rng_hi:.2f}, the market is treated as two-sided. "
                          f"A directional read needs one edge to break with follow-through.",
                supporting_conditions=(_structure_line(obs),),
                confirmation_requirements=(f"A rejection of either edge of {rng_lo:.2f}-{rng_hi:.2f} "
                                           f"on M5 before a directional break",),
                invalidation_conditions=(f"M5 closes beyond {rng_hi:.2f} or {rng_lo:.2f} with a displacement bar, "
                                         f"which would end the range read",),
                key_area_refs=tuple(_area_label(a) for a in areas if a.relation in ("INSIDE", "APPROACHING"))[:3],
                event_refs=refs(ref_kinds_range),
            ))
    return tuple(scenarios)
