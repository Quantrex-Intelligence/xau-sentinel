"""Analysis Engine V2 sequence layer: what happened after each liquidity sweep.

The calculation is the existing primitive, analysis/sequence.py::evaluate_sequence,
which locates each step on its own CLOSED bar, in order, from the sweep bar, and
applies the existing invalidation. This module does not recompute any of it. It
calls that primitive once per sweep and turns the result into a typed description:
which steps are confirmed, which are still waiting, and whether the sequence was
invalidated or superseded by a later opposite sweep.

It describes what happened. It does not decide whether a trade is valid, and it
holds no A+ rule.
"""
from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple

import pandas as pd

from analysis.liquidity import LiquidityEvent
from analysis.structure import compute_atr
from analysis.sequence import SequenceResult, evaluate_sequence

BULLISH, BEARISH = "bullish", "bearish"
CONFIRMED, WAITING, INVALIDATED, NOT_REACHED = "CONFIRMED", "WAITING", "INVALIDATED", "NOT_REACHED"
STEP_ORDER = ("SWEEP", "STRUCTURE_SHIFT", "DISPLACEMENT", "RETRACEMENT")
# Both valid orders of the structure shift and the displacement after a sweep. Neither is preferred;
# the order is recorded so the sequence stays factual.
MSS_FIRST, DISPLACEMENT_FIRST, SIMULTANEOUS = "MSS_FIRST", "DISPLACEMENT_FIRST", "SIMULTANEOUS"


@dataclass(frozen=True)
class SequenceStep:
    name: str  # one of STEP_ORDER
    status: str  # CONFIRMED | WAITING | INVALIDATED | NOT_REACHED
    bar_time: Optional[pd.Timestamp]  # UTC open time of the closed bar that confirmed the step
    level: Optional[float]
    detail: str


@dataclass(frozen=True)
class MarketSequence:
    direction: str  # bullish | bearish
    sweep: LiquidityEvent  # the sweep that starts the sequence
    steps: Tuple[SequenceStep, ...]
    stage: str  # the last confirmed step, or INVALIDATED
    is_complete: bool  # all four steps confirmed and not invalidated
    invalidated: bool
    invalidation_reason: str
    superseded_by: Optional[pd.Timestamp]  # time of a later opposite sweep, if any
    chronology_ok: bool  # step bars are in order and not before the sweep
    evidence: SequenceResult = field(compare=False)  # the existing primitive's result, kept unchanged
    # Descriptive only. These describe the sweep and the timing; they never change the candidate or A+.
    sweep_depth_atr: Optional[float] = None  # how far the sweep bar pierced the level, in ATR at the sweep
    bars_since_sweep: Optional[int] = None  # closed bars from the sweep bar to the latest closed bar
    bars_sweep_to_shift: Optional[int] = None  # closed bars from the sweep bar to the structure shift
    ordering: Optional[str] = None  # MSS_FIRST | DISPLACEMENT_FIRST | SIMULTANEOUS; None until both have happened
    # Set when another sweep owns this sequence's structure shift (see build_sequences). This sweep then does not confirm it.
    mss_owner_time: Optional[pd.Timestamp] = None

    @property
    def next_step(self) -> Optional[str]:
        for step in self.steps:
            if step.status in (WAITING,):
                return step.name
        return None


def _bar_time(m5: pd.DataFrame, index: Optional[int]) -> Optional[pd.Timestamp]:
    if index is None:
        return None
    return pd.Timestamp(m5["time"].iloc[index])


def _describe(raw: SequenceResult, m5: pd.DataFrame, direction: str) -> Tuple[SequenceStep, ...]:
    buy = direction == BULLISH
    steps: List[SequenceStep] = []

    # 1. The sweep itself is the start of the sequence, so it is always confirmed.
    steps.append(SequenceStep("SWEEP", CONFIRMED, _bar_time(m5, raw.sweep_index), None,
                              "liquidity swept on the closed bar"))

    # 2. Structure shift: a close beyond the last opposing swing confirmed before the sweep.
    if raw.invalidated:
        mss_status = CONFIRMED if raw.mss_index is not None else NOT_REACHED
    elif raw.mss_index is not None:
        mss_status = CONFIRMED
    else:
        mss_status = WAITING
    side = "above" if buy else "below"
    steps.append(SequenceStep(
        "STRUCTURE_SHIFT", mss_status, _bar_time(m5, raw.mss_index), raw.mss_level,
        (f"closed {side} the {raw.mss_level:.2f} swing" if raw.mss_index is not None and raw.mss_level is not None
         else (f"waiting for a close {side} the {raw.mss_level:.2f} swing"
               if raw.mss_level is not None else "no opposing swing confirmed before the sweep"))))

    # 3. Displacement: an outsized candle in the sequence direction, on or after the sweep.
    if raw.invalidated:
        disp_status = CONFIRMED if raw.displacement_index is not None else NOT_REACHED
    elif raw.displacement_index is not None:
        disp_status = CONFIRMED
    else:
        disp_status = WAITING
    steps.append(SequenceStep(
        "DISPLACEMENT", disp_status, _bar_time(m5, raw.displacement_index), None,
        "outsized candle in the sequence direction" if raw.displacement_index is not None
        else "waiting for an outsized candle in the sequence direction"))

    # 4. Retracement: measured on the latest closed bar, only after the MSS and displacement bars.
    if raw.invalidated:
        ret_status = NOT_REACHED
    elif raw.retracement_ok:
        ret_status = CONFIRMED
    else:
        ret_status = WAITING
    if raw.retrace_pct is None:
        ret_detail = "not yet measurable"
    elif raw.retracement_ok:
        ret_detail = f"latest close retraced {raw.retrace_pct:.0%} of the impulse, inside the configured band"
    else:
        ret_detail = f"latest close retraced {raw.retrace_pct:.0%} of the impulse; not yet inside the band"
    steps.append(SequenceStep("RETRACEMENT", ret_status, _bar_time(m5, m5.shape[0] - 1) if raw.retracement_ok else None,
                              None, ret_detail))
    return tuple(steps)


def _out_of_order_steps(steps: Tuple[SequenceStep, ...]) -> Tuple[SequenceStep, ...]:
    """Steps that occurred out of order are not counted. Only the sweep, which starts the
    sequence, stays confirmed; the later steps read as not reached so they can never show as
    confirmed evidence."""
    reason = "out of order: this step is not counted because the steps did not occur in sequence"
    return tuple(st if st.name == "SWEEP" else
                 SequenceStep(st.name, NOT_REACHED, None, st.level, reason) for st in steps)


def _chronology_ok(raw: SequenceResult, m5: pd.DataFrame) -> bool:
    """Chronology is validated, and both valid orders pass. A counted step must not come before the
    sweep bar. When a retracement is counted it must be strictly after BOTH the structure shift and the
    displacement it measures, which requires both to exist. Either order of the structure shift and
    the displacement is valid (see _ordering)."""
    if raw.sweep_index is None or raw.sweep_index < 0:
        return False
    n = len(m5)
    present = [i for i in (raw.mss_index, raw.displacement_index) if i is not None]
    if any(i < raw.sweep_index or i >= n for i in present):
        return False
    if raw.retracement_ok:
        if raw.mss_index is None or raw.displacement_index is None:
            return False
        if not (n - 1) > max(raw.mss_index, raw.displacement_index):
            return False
    return True


def _ordering(raw: SequenceResult) -> Optional[str]:
    """The factual order of the structure shift and the displacement, once both have happened."""
    m, d = raw.mss_index, raw.displacement_index
    if m is None or d is None:
        return None
    if m == d:
        return SIMULTANEOUS
    return MSS_FIRST if m < d else DISPLACEMENT_FIRST


def build_sequences(m5_closed: pd.DataFrame, sweeps: Sequence[LiquidityEvent]) -> Tuple[MarketSequence, ...]:
    """One MarketSequence per distinct sweep. `m5_closed` must be closed bars only.
    Duplicate sweeps (same time, kind and level) are described once.

    MSS ownership: one structure shift (a bar of the same direction) belongs to ONE sequence. When
    several sweeps of the same direction are shown the same shift, it belongs to the most recent of
    them that precedes it (the largest sweep index at or before the shift bar). The others keep their
    evidence, but their structure shift reads as not reached and their retracement is not counted."""
    if m5_closed is None or len(m5_closed) == 0 or not sweeps:
        return ()
    m5 = m5_closed.reset_index(drop=True)
    atr = compute_atr(m5)
    seen, ordered = set(), []
    for s in sorted(sweeps, key=lambda e: e.time):
        key = (s.kind, pd.Timestamp(s.time), round(float(s.level_price), 2))
        if key not in seen:
            seen.add(key)
            ordered.append(s)

    rows = []  # (sweep, direction, raw) for every sweep the primitive can locate
    for s in ordered:
        direction = BULLISH if s.kind == "sweep_low" else BEARISH
        raw = evaluate_sequence(m5, s, "BUY" if direction == BULLISH else "SELL")
        if raw.sweep_index is None:
            continue  # the sweep bar is not in the closed series; nothing can be described
        rows.append((s, direction, raw))

    # Ownership: for each (direction, structure-shift bar), the owner is the latest sweep at or before it.
    owner_of = {}
    for i, (s, direction, raw) in enumerate(rows):
        if raw.mss_index is None:
            continue
        key = (direction, raw.mss_index)
        cur = owner_of.get(key)
        if cur is None or raw.sweep_index > rows[cur][2].sweep_index:
            owner_of[key] = i

    out: List[MarketSequence] = []
    for i, (s, direction, raw) in enumerate(rows):
        owner_idx = owner_of.get((direction, raw.mss_index)) if raw.mss_index is not None else None
        owner_time = None
        if owner_idx is not None and owner_idx != i:
            owner_time = pd.Timestamp(rows[owner_idx][0].time)
            raw = replace(raw, mss_index=None, retracement_ok=False, retrace_pct=None)
        chronology = _chronology_ok(raw, m5)
        steps = list(_describe(raw, m5, direction))
        if owner_time is not None:
            steps = [SequenceStep("STRUCTURE_SHIFT", NOT_REACHED, None, st.level,
                                  f"owned by the later {'bullish' if direction == BULLISH else 'bearish'} sweep at "
                                  f"{owner_time:%H:%M} UTC; this sweep does not confirm it")
                     if st.name == "STRUCTURE_SHIFT" else st for st in steps]
        steps = tuple(steps)
        if not chronology and not raw.invalidated:
            steps = _out_of_order_steps(steps)
        later_opposite = [o for o in ordered if pd.Timestamp(o.time) > pd.Timestamp(s.time)
                          and (o.kind == "sweep_high") == (direction == BULLISH)]
        superseded = pd.Timestamp(later_opposite[0].time) if later_opposite else None
        invalidated = bool(raw.invalidated)
        complete = (not invalidated) and all(st.status == CONFIRMED for st in steps)
        if invalidated:
            stage = INVALIDATED
        else:
            confirmed = [st for st in steps if st.status == CONFIRMED and st.bar_time is not None]
            stage = (max(confirmed, key=lambda st: (st.bar_time, STEP_ORDER.index(st.name))).name
                     if confirmed else "SWEEP")
        sidx = raw.sweep_index
        atr_at_sweep = float(atr.iloc[sidx]) if pd.notna(atr.iloc[sidx]) and atr.iloc[sidx] > 0 else None
        if atr_at_sweep is None:
            depth = None
        elif direction == BULLISH:
            depth = round(max(0.0, (float(s.level_price) - float(m5["low"].iloc[sidx])) / atr_at_sweep), 4)
        else:
            depth = round(max(0.0, (float(m5["high"].iloc[sidx]) - float(s.level_price)) / atr_at_sweep), 4)
        out.append(MarketSequence(
            direction=direction, sweep=s, steps=steps, stage=stage, is_complete=complete,
            invalidated=invalidated, invalidation_reason=raw.invalidation_reason or "",
            superseded_by=superseded, chronology_ok=chronology, evidence=raw,
            sweep_depth_atr=depth,
            bars_since_sweep=(len(m5) - 1) - sidx,
            bars_sweep_to_shift=(raw.mss_index - sidx) if raw.mss_index is not None else None,
            ordering=_ordering(raw),
            mss_owner_time=owner_time,
        ))
    return tuple(out)


# --- factual wording (no trade language) ---------------------------------------------

_SIDE_WORDS = {BULLISH: "Sell-side liquidity was swept", BEARISH: "Buy-side liquidity was swept"}
_NEXT_WORDS = {
    "STRUCTURE_SHIFT": "Structure shift has not yet been confirmed.",
    "DISPLACEMENT": "Displacement has not yet been confirmed.",
    "RETRACEMENT": "Retracement has not yet been confirmed.",
}
_ORDER_WORDS = {
    MSS_FIRST: "Order: structure shift came before displacement.",
    DISPLACEMENT_FIRST: "Order: displacement came before the structure shift.",
    SIMULTANEOUS: "Order: structure shift and displacement closed on the same bar.",
}
_STEP_LABEL = {"SWEEP": "sweep", "STRUCTURE_SHIFT": "structure shift", "DISPLACEMENT": "displacement",
               "RETRACEMENT": "retracement"}


def sequence_wording(seq: MarketSequence) -> dict:
    """Factual statements built only from the sequence's own fields. `observed` states
    what the market did, `sequence` lists the confirmed steps, and `conditional` says
    what has not yet happened. None of this recommends an action."""
    observed = f"{_SIDE_WORDS[seq.direction]}."
    # Confirmed steps are listed in the order they happened on the closed bars, not in a fixed order.
    confirmed = [st.name for st in sorted((st for st in seq.steps if st.status == CONFIRMED),
                                          key=lambda st: (st.bar_time, STEP_ORDER.index(st.name)))]
    sequence_line = " → ".join(_STEP_LABEL[n].capitalize() if i == 0 else _STEP_LABEL[n]
                               for i, n in enumerate(confirmed)) + "."
    if seq.ordering is not None:
        sequence_line += " " + _ORDER_WORDS[seq.ordering]
    if seq.invalidated:
        conditional = f"Invalidated: {seq.invalidation_reason}"
    elif not seq.chronology_ok:
        conditional = "The steps after the sweep occurred out of order, so none of them is counted as confirmed."
    elif seq.is_complete:
        conditional = "All four steps are confirmed on closed bars."
    else:
        conditional = _NEXT_WORDS.get(seq.next_step or "", "")
    if seq.superseded_by is not None:
        conditional = (conditional + " " if conditional else "") + \
            f"A later opposite sweep occurred at {seq.superseded_by:%H:%M} UTC."
    if seq.mss_owner_time is not None:
        conditional = (conditional + " " if conditional else "") + \
            f"The structure shift is counted for the later sweep at {seq.mss_owner_time:%H:%M} UTC."
    evidence = (f"Sweep pierced the level by {seq.sweep_depth_atr:.2f} ATR; "
                f"{seq.bars_since_sweep} closed bars since the sweep"
                + (f"; structure shift {seq.bars_sweep_to_shift} bars after the sweep."
                   if seq.bars_sweep_to_shift is not None else ".")
                if seq.sweep_depth_atr is not None and seq.bars_since_sweep is not None else "")
    return {"observed": observed, "sequence": sequence_line, "conditional": conditional.strip(),
            "evidence": evidence}
