"""Layer 6 of Analysis Engine V2: deterministic market narrative.

Written from the structured results only, in a fixed section order, with every
list sorted explicitly. Same inputs always give the same text. No LLM is used.

Wording is plain English for a discretionary reader. Each event is described
from its kind, direction and level, so the reader never has to guess what a
bare "bullish" refers to. Broken levels say which role they now play. The text
states what happened. It does not say what will happen next.
"""
from typing import List, Optional, Sequence

from analysis.v2.confluence import Confluence
from analysis.v2.context import MarketContext
from analysis.v2.events import Event, dedupe_events
from analysis.v2.observations import Observations
from analysis.v2.relations import AreaState

MAX_EVENTS = 5
MAX_AREAS = 3


def _level(price: Optional[float]) -> str:
    return f"{price:.2f}" if price is not None else "the level"


def event_text(e: Event) -> str:
    """What happened, in plain words. Built from the event's kind, direction and
    level rather than from its raw detail string."""
    up = e.direction == "bullish"
    if e.kind == "BREAKOUT":
        return f"closed {'above' if up else 'below'} {_level(e.price)}"
    if e.kind == "FAILED_BREAKOUT":
        if up:
            return f"failed break below {_level(e.price)} and closed back above it"
        return f"failed break above {_level(e.price)} and closed back below it"
    if e.kind == "REJECTION":
        if up:
            return f"wick below {_level(e.price)} rejected, price held above it"
        return f"wick above {_level(e.price)} rejected, price held below it"
    if e.kind == "RETEST":
        if up:
            return f"came back to {_level(e.price)} from above and held above it"
        return f"came back to {_level(e.price)} from below and held below it"
    if e.kind == "BOS":
        return f"break of structure to the {'upside' if up else 'downside'}"
    if e.kind == "MSS":
        return f"structure shift to the {'upside' if up else 'downside'}"
    if e.kind == "SWEEP":
        return e.detail
    if e.kind == "DISPLACEMENT":
        return f"displacement {'up' if up else 'down'}"
    if e.kind == "VOLATILITY_EXPANSION":
        return "volatility expanded"
    if e.kind == "VOLATILITY_CONTRACTION":
        return "volatility contracted"
    if e.kind == "COMPRESSION":
        return "range compressed"
    if e.kind == "RANGE_EXPANSION":
        side = {"bullish": " up", "bearish": " down"}.get(e.direction or "", "")
        return f"range expanded{side}"
    if e.kind == "MOMENTUM_LOSS":
        return f"momentum fading after a {'bullish' if up else 'bearish'} run"
    if e.kind == "PULLBACK":
        return e.detail
    return e.detail or e.kind.lower().replace("_", " ")


def event_line(e: Event) -> str:
    return f"{e.time:%H:%M} UTC {e.timeframe}: {event_text(e)}"


def _area_phrase(a: AreaState, price: Optional[float]) -> str:
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
        if _last_break(a) == "bullish":
            role = "now support" if price is not None and price > high else "broken upward"
        else:
            role = "now resistance" if price is not None and price < low else "broken downward"
        text = role
    else:
        text = "relation unknown"
    return f"{span} ({text})"


def _last_break(a: AreaState) -> Optional[str]:
    breaks = [e for e in a.events if e.kind == "BREAKOUT"]
    return breaks[-1].direction if breaks else None


def _dedupe(events: Sequence[Event]) -> List[Event]:
    """Same identity rule the structured API uses (see events.event_identity)."""
    return dedupe_events(sorted(events, key=lambda e: (e.time, e.kind, e.detail)))


def build_narrative(obs: Observations, context: MarketContext, confluence: Confluence,
                    areas: Sequence[AreaState], events: Sequence[Event]) -> List[str]:
    lines: List[str] = []
    s = obs.structure
    price = obs.current_price

    lines.append(f"Direction: {context.direction.detail}")
    lines.append("Structure: H4 {}, H1 {}, M15 {}, M5 {}.".format(
        s["H4"].state.lower(), s["H1"].state.lower(), s["M15"].state.lower(), s["M5"].state.lower()))
    if confluence.cross_timeframe_conflicts:
        lines.append("Structure conflicts across timeframes: " + "; ".join(confluence.cross_timeframe_conflicts) + ".")
    # A volatility-only regime label would repeat the Volatility line below, so it is left out.
    if "VOLATILITY" not in context.regime.state:
        lines.append(f"Regime: {context.regime.state.lower()}.")
    lines.append(f"Price location: {context.price_location.detail}")

    nearby = sorted(areas, key=lambda a: abs(a.distance_atr) if a.distance_atr is not None else 1e9)[:MAX_AREAS]
    if nearby:
        lines.append("Nearby key areas: " + "; ".join(_area_phrase(a, price) for a in nearby) + ".")
    else:
        lines.append("Nearby key areas: none identified from the current data.")

    recent = _dedupe(events)[-MAX_EVENTS:]
    if recent:
        lines.append("Recent events: " + "; ".join(event_line(e) for e in recent) + ".")
    else:
        lines.append("Recent events: none detected in the recent closed bars.")

    lines.append(f"Liquidity: {context.liquidity.detail}")
    lines.append(f"Volatility: {context.volatility.state.lower().replace('_', ' ')}. {context.volatility.detail}")
    lines.append(f"Volume: {context.volume.state.lower()}. {context.volume.detail}")
    lines.append(f"Momentum: {context.momentum.state.lower()}. {context.momentum.detail}")
    lines.append(f"Session: {context.session.state}.")

    if confluence.supporting:
        lines.append("Supporting evidence: " + "; ".join(sorted(f"{l.source} ({l.lean})" for l in confluence.supporting)) + ".")
    if confluence.contradicting:
        lines.append("Contradictory evidence: " + "; ".join(sorted(f"{l.source} ({l.lean})" for l in confluence.contradicting)) + ".")
    if confluence.reference is None:
        lines.append("No dominant direction, so neither side is used as a reference.")
    if obs.data_issues:
        lines.append("Data limits: " + "; ".join(obs.data_issues) + ".")
    return lines


def narrative_text(lines: Sequence[str]) -> str:
    return "\n".join(lines)
