"""Regression tests for the audit fixes to Analysis Engine V2 (P0-P8).

P0 out-of-order sequences are never confirmed evidence for the A+ decision.
P1 a scenario whose invalidation is already met is INVALIDATED, judged on the last closed close.
P2 the same bar, kind and direction across nearby areas collapse into one event, levels kept.
P3 deterministic tiers, bounded counts, FILLED FVGs removed, time order in the output.
P5 key areas are active only within ACTIVE_AREA_ATR of price.
P6 RETEST wording says "returned to" only when the bar reached the level.
P7 a later opposite state event supersedes an earlier one on the same area, history kept.
P8 find_fvgs never carries a previous gap's size_atr forward.
"""
import dataclasses
from dataclasses import replace

import pandas as pd

from ai.strategy.evaluator import decide_from_facts
from analysis.structure import compute_atr
from analysis.v2.events import Event, collapse_area_events
from analysis.v2.fvg import find_fvgs
from analysis.v2.models import KeyArea
from analysis.v2.priority import (
    ACTIVE_AREA_ATR, TIER_CAPS, is_active_area, prioritize_events,
)
from analysis.v2.relations import AreaState, _retest_text, classify_area
from analysis.v2.scenarios import Scenario, _finalize
from analysis.sequence import SequenceResult
from analysis.v2.sequence import CONFIRMED, DISPLACEMENT_FIRST, MSS_FIRST, build_sequences
from analysis.v2.sequence import _chronology_ok, sequence_wording
from ai.strategy.schemas import CriterionStatus
from tests.test_v2_sequence import BASE, DISP_BAR, FN_SAFE, MSS_BAR, RETRACE_BAR, _facts, _frame, _sweep

# A displacement bar that is outsized but closes BELOW the 101.5 swing, followed by the MSS bar.
# The displacement therefore happens before the structure shift: out of order.
DISP_BEFORE_MSS = (98.9, 103.5, 98.8, 101.2)
# A structure-shift bar that closes above the 101.5 swing but is not itself a displacement candle.
SMALL_MSS_BAR = (101.0, 101.7, 100.9, 101.6)


def _criteria(decision):
    return {c.name: c.status for c in decision.criteria}


# --- P0: both valid orders are accepted, invalid chronology is not ------------------------

def test_displacement_before_the_structure_shift_is_a_valid_labelled_order():
    df = _frame(BASE + [DISP_BEFORE_MSS, MSS_BAR])
    sweep = _sweep(df)
    seq = build_sequences(df, [sweep])[0]
    # Fixture precondition: the displacement really is before the MSS.
    assert seq.evidence.displacement_index < seq.evidence.mss_index
    assert seq.chronology_ok is True
    assert seq.ordering == DISPLACEMENT_FIRST
    assert all(st.status == CONFIRMED for st in seq.steps if st.name in ("SWEEP", "STRUCTURE_SHIFT", "DISPLACEMENT"))
    wording = sequence_wording(seq)
    assert wording["sequence"].startswith("Sweep → displacement → structure shift")
    assert "displacement came before the structure shift" in wording["sequence"]


def test_structure_shift_before_displacement_is_also_valid_and_labelled():
    # A small-bodied structure shift (not itself a displacement), then an outsized displacement bar.
    df = _frame(BASE + [SMALL_MSS_BAR, DISP_BAR])
    seq = build_sequences(df, [_sweep(df)])[0]
    assert seq.evidence.mss_index < seq.evidence.displacement_index
    assert seq.chronology_ok is True
    assert seq.ordering == MSS_FIRST
    assert sequence_wording(seq)["sequence"].startswith("Sweep → structure shift → displacement")


def test_a_plus_reads_both_orders_the_same_way_as_the_legacy_path():
    for rows in (BASE + [DISP_BEFORE_MSS, MSS_BAR], BASE + [MSS_BAR, DISP_BAR]):
        df = _frame(rows)
        sweep = _sweep(df)
        now = df["close_time"].iloc[-1].to_pydatetime()
        seq = build_sequences(df, [sweep])[0]
        v2 = decide_from_facts(replace(_facts(seq.evidence, sweep, df),
                                       sequence_chronology_ok=seq.chronology_ok,
                                       sequence_ordering=seq.ordering), FN_SAFE, now)
        legacy = decide_from_facts(_facts(None, sweep, df), FN_SAFE, now)
        assert _criteria(v2)["M5 MSS"] == CriterionStatus.PASSED
        assert _criteria(v2)["Displacement"] == CriterionStatus.PASSED
        assert v2.model_dump(exclude={"evaluated_at"}) == legacy.model_dump(exclude={"evaluated_at"})


def test_facts_carry_the_actual_ordering_so_a_plus_does_not_assume_mss_first():
    df = _frame(BASE + [DISP_BEFORE_MSS, MSS_BAR])
    sweep = _sweep(df)
    seq = build_sequences(df, [sweep])[0]
    facts = replace(_facts(seq.evidence, sweep, df), sequence_chronology_ok=seq.chronology_ok,
                    sequence_ordering=seq.ordering)
    assert facts.sequence_ordering == DISPLACEMENT_FIRST


def test_an_invalid_chronology_is_still_not_confirmed_evidence():
    df = _frame(BASE + [MSS_BAR, DISP_BAR])
    sweep = _sweep(df)
    now = df["close_time"].iloc[-1].to_pydatetime()
    # A structure shift recorded BEFORE its sweep is invalid chronology: it is never valid evidence.
    bad = SequenceResult(sweep_index=32, mss_index=5, mss_level=101.5, displacement_index=33)
    assert _chronology_ok(bad, df) is False
    decision = decide_from_facts(replace(_facts(bad, sweep, df), sequence_chronology_ok=False), FN_SAFE, now)
    crit = _criteria(decision)
    assert crit["M5 MSS"] != CriterionStatus.PASSED
    assert crit["Displacement"] != CriterionStatus.PASSED


def test_a_retracement_counted_without_both_inputs_is_invalid_chronology():
    df = _frame(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    no_disp = SequenceResult(sweep_index=32, mss_index=33, displacement_index=None, retracement_ok=True)
    assert _chronology_ok(no_disp, df) is False
    not_after = SequenceResult(sweep_index=32, mss_index=33, displacement_index=34, retracement_ok=True)
    assert _chronology_ok(not_after, _frame(BASE + [MSS_BAR, DISP_BAR])) is False


def test_a_plus_guard_defaults_to_in_order_so_other_sources_are_unaffected():
    df = _frame(BASE + [MSS_BAR])
    sweep = _sweep(df)
    facts = _facts(build_sequences(df, [sweep])[0].evidence, sweep, df)
    assert facts.sequence_chronology_ok is True
    assert facts.sequence_ordering is None


# --- P1: scenario invalidation already met -> INVALIDATED, judged on the last closed close --

def _scenario(checks):
    return Scenario(name="REVERSAL", direction="bearish", condition="c", supporting_conditions=(),
                    confirmation_requirements=("x",), invalidation_conditions=("y",),
                    key_area_refs=(), event_refs=(), invalidation_checks=checks)


def test_scenario_is_invalidated_when_the_last_closed_close_already_crossed_its_invalidation():
    s = _finalize(_scenario((("above", 100.0),)), last_close=101.0)
    assert s.state == "INVALIDATED"
    assert "100.00" in s.invalidated_reason and "101.00" in s.invalidated_reason


def test_scenario_stays_active_while_its_invalidation_is_not_met():
    s = _finalize(_scenario((("above", 100.0),)), last_close=99.0)
    assert s.state == "ACTIVE" and s.invalidated_reason == ""


def test_scenario_without_a_closed_close_is_not_judged_invalidated():
    assert _finalize(_scenario((("above", 100.0),)), last_close=None).state == "ACTIVE"


def test_scenario_below_side_is_judged_by_the_same_rule():
    assert _finalize(_scenario((("below", 100.0),)), last_close=99.5).state == "INVALIDATED"
    assert _finalize(_scenario((("below", 100.0),)), last_close=100.5).state == "ACTIVE"


# --- P2: same bar, kind and direction across nearby areas collapse into one event ---------

def _area_ev(price, when="2026-10-05 05:00", kind="RETEST", direction="bullish", detail=None):
    return Event(kind, "M5", pd.Timestamp(when, tz="UTC"), direction, price,
                 detail or f"returned to {price:.2f} and closed above it")


def test_nearby_area_events_with_the_same_bar_kind_and_direction_collapse_to_one_with_levels_kept():
    events = [_area_ev(100.0), _area_ev(101.0)]
    out = collapse_area_events(events, price=100.4)
    assert len(out) == 1
    assert out[0].levels == (100.0, 101.0)
    assert out[0].price == 100.0  # nearest to the current price is the representative
    assert "also at 101.00" in out[0].detail


def test_events_that_differ_in_bar_kind_or_direction_are_not_collapsed():
    out = collapse_area_events([_area_ev(100.0), _area_ev(101.0, kind="BREAKOUT"),
                                _area_ev(101.0, direction="bearish")], price=100.4)
    assert len(out) == 3


def test_non_area_events_pass_through_unchanged():
    sweep = Event("SWEEP", "M5", pd.Timestamp("2026-10-05 05:00", tz="UTC"), "bullish", 100.0, "s")
    out = collapse_area_events([sweep, _area_ev(100.0), _area_ev(100.5)], price=100.0)
    assert any(e.kind == "SWEEP" and e.detail == "s" and e.levels == () for e in out)


# --- P3: deterministic tiers, bounded counts, relevance, FILLED removed --------------------

def _structure(i, kind="SWEEP"):
    t = pd.Timestamp("2026-10-05 00:00", tz="UTC") + pd.Timedelta(minutes=5 * i)
    return Event(kind, "M5", t, "bullish", 100.0, f"{kind} {i}")


def test_tier_one_is_bounded_and_keeps_the_most_recent_events():
    events = [_structure(i, kind="SWEEP" if i % 2 else "MSS") for i in range(TIER_CAPS[1] + 5)]
    kept = prioritize_events(events, price=100.0, atr=1.0)
    assert len(kept) == TIER_CAPS[1]
    assert min(e.time for e in kept) == events[5].time  # the 5 oldest were dropped, not the newest


def test_prioritization_is_deterministic_regardless_of_input_order():
    events = [_structure(i, kind="MSS") for i in range(20)]
    assert prioritize_events(events, 100.0, 1.0) == prioritize_events(list(reversed(events)), 100.0, 1.0)


def test_area_events_beyond_the_active_distance_are_not_in_the_active_stream():
    near = Event("BREAKOUT", "M5", pd.Timestamp("2026-10-05 05:00", tz="UTC"), "bullish", 100.5, "near")
    far = Event("BREAKOUT", "M5", pd.Timestamp("2026-10-05 05:05", tz="UTC"), "bullish",
                100.0 + (ACTIVE_AREA_ATR + 2) * 1.0, "far")
    kept = prioritize_events([near, far], price=100.0, atr=1.0)
    assert [e.detail for e in kept] == ["near"]


def test_filled_fvgs_are_not_emitted_as_active_events():
    from analysis.v2.events import fvg_events
    rows = [(100, 100.5, 99.5, 100.0)] * 4
    rows += [(101.0, 103.5, 100.9, 103.0)]           # bullish gap at idx 4: low 100.9 > high 100.5
    rows += [(103.0, 103.2, 102.5, 102.6),           # then price closes BELOW the gap low: FILLED
             (102.6, 102.7, 100.0, 100.2)]
    df = _bars(rows)
    statuses = [g.status for g in find_fvgs(df, lookback=30)]
    assert "FILLED" in statuses  # precondition: the gap really is filled
    assert all("filled" not in e.detail for e in fvg_events(df))


def test_superseded_events_are_never_candidates_for_the_active_stream():
    stale = replace(_area_ev(100.5, direction="bullish"), superseded=True)
    assert prioritize_events([stale], price=100.5, atr=1.0) == ()


# --- P5: key areas are active only within ACTIVE_AREA_ATR of price ------------------------

def _area_state(distance):
    area = KeyArea(99.0, 100.0, (), "RESISTANCE", "LOW", "x")
    return AreaState(area, "ABOVE" if distance and distance > 0 else "BELOW", distance, ("r",))


def test_active_area_boundary_is_inclusive_at_the_configured_atr_distance():
    assert is_active_area(_area_state(ACTIVE_AREA_ATR))
    assert is_active_area(_area_state(-ACTIVE_AREA_ATR))
    assert not is_active_area(_area_state(ACTIVE_AREA_ATR + 0.01))
    assert not is_active_area(_area_state(None))


# --- P6 and P7: RETEST wording and same-area supersession ----------------------------------

def _bars(rows, start="2026-10-05 00:00"):
    t = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = t
    df["close_time"] = t + pd.Timedelta(minutes=5)
    df["is_closed"] = True
    df["volume"] = 100.0
    return df


RESISTANCE = KeyArea(99.0, 100.0, (), "RESISTANCE", "LOW", "x")


def _break_retest_fail(retest_low):
    rows = [
        (99.5, 99.8, 99.2, 99.6),          # before the break
        (99.7, 101.2, 99.6, 101.0),        # closes above 100 by the buffer: BREAKOUT bullish
        (101.0, 101.5, retest_low, 101.2),  # the retest bar
        (101.2, 101.3, 99.4, 99.6),        # closes back below 100: FAILED_BREAKOUT bearish
    ]
    return classify_area(RESISTANCE, _bars(rows), price=99.6, atr=4.0)


def test_retest_that_stopped_short_is_described_as_touched_within_tolerance_not_returned_to():
    state = _break_retest_fail(retest_low=100.5)  # never reaches 100.00; within 0.5 ATR (2.0) of it
    retest = [e for e in state.events if e.kind == "RETEST"][0]
    assert "touched within 0.5 ATR of 100.00" in retest.detail
    assert "returned to" not in retest.detail


def test_retest_that_reached_the_level_still_says_returned_to():
    state = _break_retest_fail(retest_low=99.9)  # the bar reached 100.00
    retest = [e for e in state.events if e.kind == "RETEST"][0]
    assert "returned to 100.00" in retest.detail
    assert _retest_text(True, 100.0, "above") == "returned to 100.00 and closed above it"


def test_a_later_opposite_failed_breakout_supersedes_the_earlier_retest_and_breakout_but_keeps_them():
    state = _break_retest_fail(retest_low=100.5)
    by_kind = {e.kind: e for e in state.events}
    assert by_kind["RETEST"].superseded is True
    assert by_kind["BREAKOUT"].superseded is True
    assert by_kind["FAILED_BREAKOUT"].superseded is False
    # Nothing is deleted from the area's own history.
    assert {"BREAKOUT", "RETEST", "FAILED_BREAKOUT"} <= {e.kind for e in state.events}


# --- P8: find_fvgs size_atr is per gap, never inherited --------------------------------------

def _two_gap_bars():
    rows = [(100, 100.5, 99.5, 100.0)] * 2
    rows += [(101.0, 103.5, 100.9, 103.0)]            # bullish gap at idx 2: low 100.9 > high 100.5
    rows += [(100, 100.5, 99.5, 100.0)] * 2           # idx 3, 4
    rows += [(105.0, 108.0, 104.9, 107.0)]            # bullish gap at idx 5: low 104.9 > high[3] 100.5
    return _bars(rows)


def _gap_at(gaps, df, idx):
    return next(g for g in gaps if g.formed_at == df["time"].iloc[idx])


def test_a_gap_without_usable_atr_does_not_inherit_the_previous_gaps_size(monkeypatch):
    import analysis.v2.fvg as fvg_mod
    df = _two_gap_bars()
    # Only bar 2 has a usable ATR (2.0). Every other bar's ATR is NaN.
    atr = pd.Series([float("nan")] * len(df))
    atr.iloc[2] = 2.0
    monkeypatch.setattr(fvg_mod, "compute_atr", lambda _df: atr)
    gaps = find_fvgs(df, lookback=30)
    assert _gap_at(gaps, df, 2).size_atr == round((100.9 - 100.5) / 2.0, 4)
    # The later gaps (idx 4 bearish, idx 5 bullish) have no ATR and must not inherit idx 2's size.
    assert _gap_at(gaps, df, 5).size_atr is None
    assert all(g.size_atr is None for g in gaps if g.formed_at != df["time"].iloc[2])


def test_a_first_gap_without_usable_atr_gets_no_size_and_does_not_crash(monkeypatch):
    import analysis.v2.fvg as fvg_mod
    df = _two_gap_bars()
    atr = pd.Series([float("nan")] * len(df))  # no ATR anywhere
    monkeypatch.setattr(fvg_mod, "compute_atr", lambda _df: atr)
    gaps = find_fvgs(df, lookback=30)
    assert _gap_at(gaps, df, 2) is not None
    assert all(g.size_atr is None for g in gaps)
