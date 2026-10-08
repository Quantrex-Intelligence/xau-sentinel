"""Layer 5 of Analysis Engine V2: confluence and contradictions.

Every piece of evidence is listed with its source and timeframe and leans
bullish, bearish, or neutral. The output is two lists per direction plus the
reference direction. There is no score, weight, count-based grade or
percentage. An item is either supporting, contradicting, or neutral relative
to the reference. Volume has no direction, so it is always neutral: it can
describe how active the market is, but it can never support or oppose a
direction on its own.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from analysis.v2.context import MarketContext
from analysis.v2.relations import AreaState

BULLISH, BEARISH, NEUTRAL = "bullish", "bearish", "neutral"
_TREND_TO_LEAN = {"UP": BULLISH, "DOWN": BEARISH, "NONE": None}


@dataclass(frozen=True)
class Lean:
    source: str  # e.g. "H1 structure", "M5 MSS", "nearest resistance"
    timeframe: str  # M5 | M15 | H1 | H4 | "" when not timeframe-specific
    lean: str  # bullish | bearish | neutral
    detail: str


@dataclass(frozen=True)
class Confluence:
    reference: Optional[str]  # bullish | bearish | None when no trend is established
    reference_reason: str
    supporting: Tuple[Lean, ...]
    contradicting: Tuple[Lean, ...]
    neutral: Tuple[Lean, ...]
    bullish: Tuple[Lean, ...]
    bearish: Tuple[Lean, ...]
    cross_timeframe_conflicts: Tuple[str, ...]


def _structure_leans(obs) -> List[Lean]:
    out: List[Lean] = []
    for tf in ("H4", "H1", "M15", "M5"):
        s = obs.structure[tf]
        if s.state == "BULLISH":
            lean = BULLISH
        elif s.state == "BEARISH":
            lean = BEARISH
        else:
            lean = NEUTRAL
        out.append(Lean(f"{tf} structure", tf, lean, f"{s.state}: {s.reason}"))
        if s.last_bos:
            out.append(Lean(f"{tf} BOS", tf, s.last_bos, f"latest {tf} structure break is {s.last_bos}"))
        if s.last_mss:
            out.append(Lean(f"{tf} MSS", tf, s.last_mss, f"latest {tf} structure shift is {s.last_mss}"))
    return out


def _level_text(a: AreaState) -> str:
    return f"{a.area.low:.2f}" if a.area.low == a.area.high else f"{a.area.low:.2f}-{a.area.high:.2f}"


def _consolidated_breaks(areas: List[AreaState]) -> List[Lean]:
    """Broken levels that belong to one directional move become ONE lean per direction. Every
    BROKEN area is a break that is still on its far side, and all breaks in the same direction within
    the recent window are one continuing move, so counting each level as its own observation
    overstated the evidence. Levels are kept in the detail as evidence. Opposite directions stay as
    separate leans, because they really are contradictory."""
    by_direction: dict = {}
    for a in areas:
        if a.relation != "BROKEN":
            continue
        breaks = [e for e in a.events if e.kind == "BREAKOUT" and not e.superseded]
        if breaks:
            by_direction.setdefault(breaks[-1].direction, []).append(a)

    out: List[Lean] = []
    for direction in ("bullish", "bearish"):
        group = sorted(by_direction.get(direction, []), key=lambda a: a.area.mid)
        if not group:
            continue
        levels = ", ".join(_level_text(a) for a in group)
        verb = "above" if direction == "bullish" else "below"
        side = "still above" if direction == "bullish" else "still below"
        out.append(Lean(f"broken levels ({len(group)})", "M5", direction,
                        f"closed {verb} {levels} in the recent window; price is {side} them"))
    return out


def _event_leans(obs, context: MarketContext, events, areas: List[AreaState]) -> List[Lean]:
    out: List[Lean] = []
    sweeps = sorted((e for e in events if e.kind == "SWEEP"), key=lambda e: e.time)
    if sweeps:
        last = sweeps[-1]
        out.append(Lean("latest sweep", "M5", last.direction, last.detail))
    if obs.displacement_m5:
        out.append(Lean("M5 displacement", "M5", obs.displacement_m5,
                        f"last closed M5 bar is a {obs.displacement_m5} displacement"))
    mom = context.momentum
    if mom.state == "ACCELERATING":
        out.append(Lean("momentum", "M5", BULLISH if "net direction up" in mom.detail else BEARISH, mom.detail))
    elif mom.state == "FADING":
        out.append(Lean("momentum", "M5", NEUTRAL, mom.detail))
    loc = context.price_location.state
    if loc == "ABOVE_PREVIOUS_DAY_HIGH":
        out.append(Lean("price location", "D1", BULLISH, context.price_location.detail))
    elif loc == "BELOW_PREVIOUS_DAY_LOW":
        out.append(Lean("price location", "D1", BEARISH, context.price_location.detail))
    out.extend(_consolidated_breaks(areas))
    for a in areas:
        if a.relation == "REJECTING":
            rej = [e for e in a.events if e.kind == "REJECTION"]
            lean = rej[-1].direction if rej else NEUTRAL
            out.append(Lean(f"rejected area {a.area.low:.2f}-{a.area.high:.2f}", "M5", lean, " ".join(a.reasons)))
    out.append(Lean("volume", "M5", NEUTRAL,
                    "Tick volume describes activity only; it has no direction and cannot confirm one."))
    return out


def build_confluence(obs, context: MarketContext, events, areas: List[AreaState]) -> Confluence:
    leans = _structure_leans(obs) + _event_leans(obs, context, events, areas)

    reference = _TREND_TO_LEAN.get(context.direction.state)
    if reference is None:
        reference_reason = "No clear trend on H1 or H4, so no direction is treated as the reference."
    else:
        reference_reason = f"Reference is the {context.direction.state.lower()} trend: {context.direction.detail}"

    bullish = tuple(l for l in leans if l.lean == BULLISH)
    bearish = tuple(l for l in leans if l.lean == BEARISH)
    neutral = tuple(l for l in leans if l.lean == NEUTRAL)
    if reference is None:
        supporting: Tuple[Lean, ...] = ()
        contradicting: Tuple[Lean, ...] = ()
    else:
        supporting = tuple(l for l in leans if l.lean == reference)
        contradicting = tuple(l for l in leans if l.lean not in (reference, NEUTRAL))

    conflicts = []
    struct_tfs = [("H4", obs.structure["H4"].state), ("H1", obs.structure["H1"].state),
                  ("M15", obs.structure["M15"].state), ("M5", obs.structure["M5"].state)]
    for i, (tf_a, st_a) in enumerate(struct_tfs):
        for tf_b, st_b in struct_tfs[i + 1:]:
            if {st_a, st_b} == {"BULLISH", "BEARISH"}:
                conflicts.append(f"{tf_a} {st_a} vs {tf_b} {st_b}")

    return Confluence(
        reference=reference, reference_reason=reference_reason,
        supporting=supporting, contradicting=contradicting, neutral=neutral,
        bullish=bullish, bearish=bearish,
        cross_timeframe_conflicts=tuple(conflicts),
    )
