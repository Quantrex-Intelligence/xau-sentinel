"""MSS ownership: one structure shift belongs to one sweep sequence.

When several sweeps of the same direction are followed by the same structure-shift bar, the shift
belongs to the most recent of them that precedes it. The others keep their evidence, but their
structure shift is not confirmed by it and their retracement is not counted.
"""
from dataclasses import replace

import pandas as pd

from ai.strategy.evaluator import decide_from_facts
from ai.strategy.schemas import CriterionStatus
from analysis.liquidity import LiquidityEvent
from analysis.v2.sequence import CONFIRMED, NOT_REACHED, build_sequences, sequence_wording
from tests.test_v2_sequence import BASE, DISP_BAR, FN_SAFE, MSS_BAR, RETRACE_BAR, _facts, _frame, _sweep

SWEEP2_BAR = (99.5, 99.7, 98.7, 99.2)  # a second bullish sweep bar; it closes below the 101.5 swing


def _shared_mss_frame():
    """Sweep 1 on bar 32, sweep 2 on bar 33; both search the same 101.5 swing and find the MSS on bar 34."""
    df = _frame(BASE + [SWEEP2_BAR, MSS_BAR, DISP_BAR, RETRACE_BAR])
    s1 = _sweep(df)  # bar 32
    s2 = LiquidityEvent(df["time"].iloc[33], "Second level swept", "Second level", 98.7, "sweep_low")
    return df, s1, s2


def _by_sweep(seqs, sweep):
    return next(s for s in seqs if s.sweep.time == sweep.time)


def test_the_most_recent_preceding_sweep_owns_the_shared_structure_shift():
    df, s1, s2 = _shared_mss_frame()
    seqs = build_sequences(df, [s1, s2])
    earlier, later = _by_sweep(seqs, s1), _by_sweep(seqs, s2)

    # Fixture precondition: both sweeps really do see the same shift bar.
    assert earlier.evidence.mss_index is None  # the owner is the later sweep, see below
    assert later.evidence.mss_index == 34
    assert later.mss_owner_time is None
    assert [st.status for st in later.steps if st.name == "STRUCTURE_SHIFT"] == [CONFIRMED]


def test_the_earlier_sweep_keeps_its_evidence_but_does_not_confirm_the_shared_shift():
    df, s1, s2 = _shared_mss_frame()
    earlier = _by_sweep(build_sequences(df, [s1, s2]), s1)
    assert earlier.mss_owner_time == s2.time
    mss_step = next(st for st in earlier.steps if st.name == "STRUCTURE_SHIFT")
    assert mss_step.status == NOT_REACHED
    assert "owned by the later bullish sweep" in mss_step.detail
    # The sweep itself and its displacement are still real evidence for this sweep.
    assert next(st for st in earlier.steps if st.name == "SWEEP").status == CONFIRMED
    assert "counted for the later sweep" in sequence_wording(earlier)["conditional"]


def test_exactly_one_sequence_confirms_the_shared_structure_shift():
    df, s1, s2 = _shared_mss_frame()
    seqs = build_sequences(df, [s1, s2])
    confirmed_at = [s.sweep.time for s in seqs
                    for st in s.steps if st.name == "STRUCTURE_SHIFT" and st.status == CONFIRMED]
    assert confirmed_at == [s2.time]


def test_ownership_does_not_depend_on_the_order_the_sweeps_are_given():
    df, s1, s2 = _shared_mss_frame()
    a = build_sequences(df, [s1, s2])
    b = build_sequences(df, [s2, s1])
    assert [(s.sweep.time, s.mss_owner_time, s.steps) for s in a] == \
           [(s.sweep.time, s.mss_owner_time, s.steps) for s in b]


def test_a_non_owner_cannot_confirm_the_shift_when_the_a_plus_decision_reads_its_evidence():
    df, s1, s2 = _shared_mss_frame()
    now = df["close_time"].iloc[-1].to_pydatetime()
    earlier = _by_sweep(build_sequences(df, [s1, s2]), s1)
    decision = decide_from_facts(replace(_facts(earlier.evidence, s1, df),
                                         sequence_chronology_ok=earlier.chronology_ok,
                                         sequence_ordering=earlier.ordering), FN_SAFE, now)
    crit = {c.name: c.status for c in decision.criteria}
    assert crit["M5 MSS"] != CriterionStatus.PASSED


def test_a_sweep_of_the_opposite_direction_does_not_compete_for_the_shift():
    df, s1, _ = _shared_mss_frame()
    bearish = LiquidityEvent(df["time"].iloc[33], "Bearish level", "Bearish level", 102.0, "sweep_high")
    seqs = build_sequences(df, [s1, bearish])
    bull = _by_sweep(seqs, s1)
    assert bull.mss_owner_time is None
    assert bull.evidence.mss_index == 34


def test_a_single_sweep_owns_its_own_shift():
    df = _frame(BASE + [MSS_BAR, DISP_BAR])
    seq = build_sequences(df, [_sweep(df)])[0]
    assert seq.mss_owner_time is None
    assert seq.evidence.mss_index == 33
