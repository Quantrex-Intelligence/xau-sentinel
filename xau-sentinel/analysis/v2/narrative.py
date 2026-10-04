"""Layer 6 of Analysis Engine V2: deterministic market narrative.

Written from the structured results only, in a fixed section order, with every
list sorted explicitly. Same inputs always give the same text. No LLM is used.

Wording is plain English for a reader who is not reading the code. Relation
labels are turned into sentences ("price is inside", "broken upward"), and
event lines use each event's own description, so a bare "bullish" never has to
be interpreted on its own.
"""
from typing import List, Optional, Sequence

from analysis.v2.confluence import Confluence
from analysis.v2.context import MarketContext
from analysis.v2.events import Event
from analysis.v2.observations import Observations
from analysis.v2.relations import AreaState

MAX_EVENTS = 5
MAX_AREAS = 3


def _area_phrase(a: AreaState) -> str:
    low, high = a.area.low, a.area.high
    span = f"{low:.2f}" if low == high else f"{low:.2f}-{high:.2f}"
    gap = "" if a.distance_atr is None else f", {abs(a.distance_atr):.2f} ATR away"
    if a.relation == "INSIDE":
        text = "price is inside it"
    elif a.relation == "APPROACHING":
        text = "price is approaching it" + gap
    elif a.relation == "ABOVE":
        text = "price is above it"
    elif a.relation == "BELOW":
        text = "price is below it" + gap
    elif a.relation == "REJECTING":
        text = "recently rejected; price has not moved back through it"
    elif a.relation == "BROKEN":
        text = "broken upward" if _last_break(a) == "bullish" else "broken downward"
    else:
        text = "relation unknown"
    return f"{span} ({text})"


def _last_break(a: AreaState) -> Optional[str]:
    breaks = [e for e in a.events if e.kind == "BREAKOUT"]
    return breaks[-1].direction if breaks else None


def _event_phrase(e: Event) -> str:
    """The event's own description, prefixed with the timeframe and UTC time."""
    if e.kind in ("BOS", "MSS"):
        body = f"{e.kind} {e.direction}: {e.detail}"
    else:
        body = e.detail or e.kind.lower().replace("_", " ")
    return f"{e.time:%H:%M} UTC {e.timeframe}: {body}"


def build_narrative(obs: Observations, context: MarketContext, confluence: Confluence,
                    areas: Sequence[AreaState], events: Sequence[Event]) -> List[str]:
    lines: List[str] = []
    s = obs.structure

    lines.append(f"Direction: {context.direction.detail}")
    lines.append("Structure: H4 {}, H1 {}, M15 {}, M5 {}.".format(
        s["H4"].state.lower(), s["H1"].state.lower(), s["M15"].state.lower(), s["M5"].state.lower()))
    if confluence.cross_timeframe_conflicts:
        lines.append("Structure conflicts across timeframes: " + "; ".join(confluence.cross_timeframe_conflicts) + ".")
    lines.append(f"Regime: {context.regime.state.lower()}. {context.regime.detail}")
    lines.append(f"Price location: {context.price_location.detail}")

    nearby = sorted(areas, key=lambda a: abs(a.distance_atr) if a.distance_atr is not None else 1e9)[:MAX_AREAS]
    if nearby:
        lines.append("Nearby key areas: " + "; ".join(_area_phrase(a) for a in nearby) + ".")
    else:
        lines.append("Nearby key areas: none identified from the current data.")

    seen, unique = set(), []
    for e in sorted(events, key=lambda e: (e.time, e.kind, e.detail)):
        key = (e.time, e.kind, e.direction, e.detail)
        if key not in seen:  # the same event can be reported by two areas at one bar
            seen.add(key)
            unique.append(e)
    recent = unique[-MAX_EVENTS:]
    if recent:
        lines.append("Recent events: " + "; ".join(_event_phrase(e) for e in recent) + ".")
    else:
        lines.append("Recent events: none detected in the recent closed bars.")

    lines.append(f"Liquidity: {context.liquidity.detail}")
    lines.append(f"Volatility: {context.volatility.state.lower()}. {context.volatility.detail}")
    lines.append(f"Volume: {context.volume.state.lower()}. {context.volume.detail}")
    lines.append(f"Momentum: {context.momentum.state.lower()}. {context.momentum.detail}")
    lines.append(f"Session: {context.session.state}.")

    if confluence.supporting:
        lines.append("Supporting evidence: " + "; ".join(sorted(f"{l.source} ({l.lean})" for l in confluence.supporting)) + ".")
    if confluence.contradicting:
        lines.append("Contradictory evidence: " + "; ".join(sorted(f"{l.source} ({l.lean})" for l in confluence.contradicting)) + ".")
    if confluence.reference is None:
        lines.append("No direction is treated as dominant: " + confluence.reference_reason)
    if obs.data_issues:
        lines.append("Data limits: " + "; ".join(obs.data_issues) + ".")
    return lines


def narrative_text(lines: Sequence[str]) -> str:
    return "\n".join(lines)
