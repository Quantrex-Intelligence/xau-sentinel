"""Analysis V2 sequence layer: the typed sweep → structure shift → displacement →
retracement description, its bullish and bearish forms, incomplete and interrupted
sequences, duplicate prevention, chronology, closed-bar integrity, the V2 → A+
mapping, and the decision equivalence with the legacy path."""
import re
from types import SimpleNamespace

import pandas as pd
import pytest

from analysis.liquidity import LiquidityEvent
from analysis.sequence import SequenceResult, evaluate_sequence
from analysis.structure import StructureResult, closed_only
from analysis.v2 import sequence as seq_mod
from analysis.v2.sequence import (
    BEARISH, BULLISH, CONFIRMED, INVALIDATED, NOT_REACHED, WAITING,
    build_sequences, sequence_wording,
)
from ai.strategy.evaluator import decide_from_facts
from ai.strategy.facts import StrategyFacts
from ai.v2_strategy.bridge import V2NotEvaluable, _candidate_sequence
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel

FN_SAFE = FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                           data_available=True, safety_level=SafetyLevel.SAFE, daily_loss_used_pct=10.0)

# A bullish setup: quiet warm-up for ATR, a rise to a 101.5 swing high, a pullback,
# then a sweep wick below 99.0 that closes back above it.
WARM = [(100.0 + (0.2 if i % 2 else -0.2), 100.5, 99.5, 100.0 + (0.1 if i % 2 else -0.1)) for i in range(20)]
RISE = [(99.0 + 0.4 * i, 99.5 + 0.4 * i, 98.6 + 0.4 * i, 99.2 + 0.4 * i) for i in range(6)]
PULL = [(101.0 - 0.3 * i, 101.1 - 0.3 * i, 100.4 - 0.3 * i, 100.6 - 0.3 * i) for i in range(6)]
SWEEP_BAR = (99.6, 99.8, 98.8, 99.4)
MSS_BAR = (99.4, 101.8, 99.3, 101.6)
DISP_BAR = (101.6, 106.6, 101.5, 106.4)
RETRACE_BAR = (106.4, 106.5, 103.0, 103.2)
BASE = WARM + RISE + PULL + [SWEEP_BAR]


def _frame(rows, start="2026-01-05 00:00"):
    t = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = t
    df["volume"] = 100.0
    df["close_time"] = t + pd.Timedelta(minutes=5)
    df["is_closed"] = True
    return df


def _sweep(df, kind="sweep_low", level=99.0, bar=None):
    """The sweep sits on the SWEEP_BAR (the last bar of BASE), not on the last bar of a longer
    series that adds the structure-shift, displacement and retracement bars."""
    bar = len(BASE) - 1 if bar is None else bar
    return LiquidityEvent(df["time"].iloc[bar], "Test level swept", "Test level", level, kind)


def _mirror(rows):
    """Reflects prices around 100: a bearish version of any bullish row set."""
    return [(200 - o, 200 - l, 200 - h, 200 - c) for (o, h, l, c) in rows]


def _one(rows, sweeps=None):
    df = _frame(rows)
    sw = sweeps if sweeps is not None else [_sweep(df, bar=len(BASE) - 1)]
    seqs = build_sequences(df, sw)
    assert len(seqs) == 1
    return seqs[0]


# --- bullish sequence progression -------------------------------------------------

def test_sweep_alone_is_confirmed_and_the_structure_shift_is_waiting():
    s = _one(BASE)
    assert s.direction == BULLISH and s.stage == "SWEEP" and not s.is_complete
    assert s.next_step == "STRUCTURE_SHIFT"
    statuses = {st.name: st.status for st in s.steps}
    assert statuses == {"SWEEP": CONFIRMED, "STRUCTURE_SHIFT": WAITING,
                        "DISPLACEMENT": WAITING, "RETRACEMENT": WAITING}


def test_sweep_then_structure_shift_then_displacement():
    s = _one(BASE + [MSS_BAR, DISP_BAR])
    assert s.stage == "DISPLACEMENT" and not s.is_complete
    assert s.next_step == "RETRACEMENT"
    assert {st.name: st.status for st in s.steps}["DISPLACEMENT"] == CONFIRMED


def test_complete_sequence_has_all_four_steps_confirmed_in_order():
    s = _one(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    assert s.is_complete and s.stage == "RETRACEMENT" and s.next_step is None
    assert all(st.status == CONFIRMED for st in s.steps)
    times = [st.bar_time for st in s.steps]
    assert times == sorted(times)


def test_retracement_outside_the_band_is_waiting_with_the_measured_percentage():
    shallow = (106.4, 106.5, 105.9, 106.1)  # barely retraced
    s = _one(BASE + [MSS_BAR, DISP_BAR, shallow])
    ret = next(st for st in s.steps if st.name == "RETRACEMENT")
    assert ret.status == WAITING and "not yet inside the band" in ret.detail


# --- bearish mirror ---------------------------------------------------------------

def test_bearish_sequence_is_the_mirror_of_the_bullish_one():
    rows = _mirror(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    df = _frame(rows)
    sw = [LiquidityEvent(df["time"].iloc[len(BASE) - 1], "Test level swept", "Test level", 101.0, "sweep_high")]
    s = build_sequences(df, sw)[0]
    assert s.direction == BEARISH and s.is_complete
    assert sequence_wording(s)["observed"] == "Buy-side liquidity was swept."


# --- interrupted, superseded, invalidated ----------------------------------------

def test_closing_back_beyond_the_swept_extreme_after_the_shift_invalidates_the_sequence():
    breach = (103.0, 103.1, 98.5, 98.7)  # closes below the swept low 98.8
    s = _one(BASE + [MSS_BAR, breach])
    assert s.invalidated and s.stage == INVALIDATED and not s.is_complete
    assert "closed back below the swept low" in s.invalidation_reason
    assert sequence_wording(s)["conditional"].startswith("Invalidated:")


def test_a_later_opposite_sweep_supersedes_an_earlier_sequence():
    later = (99.0, 101.9, 98.9, 101.7)  # a high sweep bar afterwards
    df = _frame(BASE + [later])
    sweeps = [_sweep(_frame(BASE)), LiquidityEvent(df["time"].iloc[-1], "High swept", "High", 101.8, "sweep_high")]
    first = next(s for s in build_sequences(df, sweeps) if s.direction == BULLISH)
    assert first.superseded_by == df["time"].iloc[-1]
    assert "later opposite sweep" in sequence_wording(first)["conditional"]


# --- duplicates and ordering -------------------------------------------------------

def test_the_same_sweep_reported_twice_is_described_once():
    df = _frame(BASE)
    sw = _sweep(df)
    assert len(build_sequences(df, [sw, sw])) == 1


def test_one_sequence_per_distinct_sweep_in_chronological_order():
    df = _frame(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR, SWEEP_BAR])
    first = LiquidityEvent(df["time"].iloc[len(BASE) - 1], "A", "A", 99.0, "sweep_low")
    second = LiquidityEvent(df["time"].iloc[-1], "B", "B", 98.8, "sweep_low")
    seqs = build_sequences(df, [second, first])
    assert [s.sweep.time for s in seqs] == [first.time, second.time]


def test_chronology_check_rejects_steps_out_of_order():
    bad = SequenceResult(sweep_index=10, mss_index=5, displacement_index=12)
    df = _frame(BASE + [MSS_BAR, DISP_BAR])
    assert seq_mod._chronology_ok(bad, df) is False
    good = SequenceResult(sweep_index=12, mss_index=13, displacement_index=14)
    assert seq_mod._chronology_ok(good, df) is True


def test_sequence_steps_never_precede_the_sweep_bar():
    s = _one(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    assert s.chronology_ok
    assert all(st.bar_time >= s.sweep.time for st in s.steps if st.bar_time is not None)


# --- closed-bar integrity -------------------------------------------------------------

def test_a_forming_bar_never_creates_or_changes_a_sequence():
    closed = _frame(BASE + [MSS_BAR, DISP_BAR])
    forming = closed.iloc[[-1]].copy()
    forming["time"] = closed["time"].iloc[-1] + pd.Timedelta(minutes=5)
    forming["close_time"] = forming["time"] + pd.Timedelta(minutes=5)
    forming["open"] = forming["high"] = forming["low"] = forming["close"] = 150.0
    forming["is_closed"] = False
    with_forming = pd.concat([closed, forming], ignore_index=True)
    sw = [_sweep(closed)]
    a = build_sequences(closed_only({"M5": closed})["M5"], sw)[0]
    b = build_sequences(closed_only({"M5": with_forming})["M5"], sw)[0]
    assert [(st.name, st.status) for st in a.steps] == [(st.name, st.status) for st in b.steps]
    assert a.stage == b.stage


def test_no_sequence_is_described_for_a_sweep_outside_the_closed_series():
    df = _frame(BASE)
    ghost = LiquidityEvent(pd.Timestamp("2030-01-01", tz="UTC"), "Ghost", "Ghost", 99.0, "sweep_low")
    assert build_sequences(df, [ghost]) == ()


def test_empty_or_missing_inputs_give_no_sequences():
    assert build_sequences(None, []) == ()
    assert build_sequences(_frame(BASE), []) == ()


# --- wording -------------------------------------------------------------------------------

def test_wording_is_factual_and_contains_no_trade_language():
    s = _one(BASE + [MSS_BAR, DISP_BAR])
    text = " ".join(sequence_wording(s).values())
    assert "Sell-side liquidity was swept." in text
    assert "Sweep → structure shift → displacement." in text
    assert "Retracement has not yet been confirmed." in text
    # "Buy-side" and "sell-side" name the liquidity that was swept; they are not trade calls.
    assert not re.search(r"\b(buy|sell)\b(?!-side)|\b(enter|long|short|target|probab|confiden|should|will|likely)\b",
                         text, re.IGNORECASE)


# --- V2 -> A+ mapping and decision equivalence -------------------------------------------

def _facts(sequence, sweep, df):
    st = StructureResult(state="BULLISH", swings=[], reason="H1 bullish")
    return StrategyFacts(h4=st, h1=st, m15=st, m5=st, zones={}, sweeps=[sweep], equal_levels=[],
                         m5_closed=df, current_price=float(df["close"].iloc[-1]), data_stale=False,
                         sequence=sequence)


def test_v2_sequence_is_exactly_the_sequence_a_plus_would_compute_itself():
    df = _frame(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    sweep = _sweep(df)
    v2 = build_sequences(df, [sweep])[0].evidence
    direct = evaluate_sequence(df, sweep, "BUY")
    assert v2 == direct


def test_candidate_mapping_picks_the_v2_sequence_for_the_candidate_sweep():
    df = _frame(BASE + [MSS_BAR, DISP_BAR])
    sweep = _sweep(df)
    analysis = SimpleNamespace(sequences=build_sequences(df, [sweep]), observations=None)
    picked = _candidate_sequence(analysis, [sweep])
    assert picked.evidence == evaluate_sequence(df, sweep, "BUY")


def test_candidate_without_a_v2_sequence_is_not_evaluable_rather_than_guessed():
    df = _frame(BASE)
    sweep = _sweep(df)
    analysis = SimpleNamespace(sequences=(), observations=None)
    with pytest.raises(V2NotEvaluable):
        _candidate_sequence(analysis, [sweep])


def test_a_plus_decision_is_identical_whether_the_sequence_comes_from_v2_or_is_computed_legacy():
    df = _frame(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    sweep = _sweep(df)
    now = df["close_time"].iloc[-1].to_pydatetime()
    v2_seq = build_sequences(df, [sweep])[0].evidence
    legacy = decide_from_facts(_facts(None, sweep, df), FN_SAFE, now).model_dump(exclude={"evaluated_at"})
    v2 = decide_from_facts(_facts(v2_seq, sweep, df), FN_SAFE, now).model_dump(exclude={"evaluated_at"})
    assert v2 == legacy


def test_a_plus_still_refuses_a_plus_when_the_sequence_is_incomplete():
    df = _frame(BASE + [MSS_BAR])
    sweep = _sweep(df)
    now = df["close_time"].iloc[-1].to_pydatetime()
    ev = decide_from_facts(_facts(build_sequences(df, [sweep])[0].evidence, sweep, df), FN_SAFE, now)
    assert ev.rating.value != "A+"


def test_sequence_output_is_deterministic():
    df = _frame(BASE + [MSS_BAR, DISP_BAR])
    sw = [_sweep(df)]
    a = build_sequences(df, sw)
    b = build_sequences(df, sw)
    assert [(s.direction, s.stage, s.steps) for s in a] == [(s.direction, s.stage, s.steps) for s in b]
