"""Setup state machine validation (spec section 15).

Uses mocks for the four underlying analysis calls (analyze_structure,
detect_sweeps, detect_displacement, compute_zones) so each state-machine
transition can be tested in isolation, independent of whether the
lower-level analysis functions themselves are correct (those have their own
dedicated test files).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import analysis.setup as setup_mod
from analysis.structure import StructureResult, analyze_structure as real_analyze_structure
from analysis.liquidity import LiquidityEvent
from analysis.sequence import SequenceResult
from tests.conftest import make_candles


def _dummy_candles():
    """Minimal 15-bar M5-shaped df — enough for _plan_trade's tail(10) lookup
    and for a last close/price to exist. Only used when the real _plan_trade
    runs (analyze_structure/detect_sweeps/detect_displacement are mocked)."""
    rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(15)]
    df = make_candles(rows)
    return {"H4": df, "H1": df, "M15": df, "M5": df}


def _patch_structure(monkeypatch, h4, h1, m15, m5):
    mock = Mock(side_effect=[h4, h1, m15, m5])
    monkeypatch.setattr(setup_mod, "analyze_structure", mock)


def _patch_sequence(monkeypatch, **fields):
    """Mocks analysis/sequence.py's bar-by-bar result (Stage 23A) — the
    source of the MSS/Displacement/Retracement checklist steps and of
    INVALIDATED. Its own scenarios are covered in tests/test_sequence.py."""
    mock = Mock(return_value=SequenceResult(**fields))
    monkeypatch.setattr(setup_mod, "evaluate_sequence", mock)
    return mock


ALL_STEPS = dict(sweep_index=5, mss_index=7, displacement_index=7, retracement_ok=True)


def _fresh_now(candles):
    """A `now` one minute after the newest M5 candle — a live, non-stale feed
    for these fixed-date fixtures (Stage 23A, VAL-011)."""
    return candles["M5"]["time"].iloc[-1].to_pydatetime() + timedelta(minutes=1)


def _sr(state, last_mss=None, last_bos=None, reason=""):
    return StructureResult(state=state, last_mss=last_mss, last_bos=last_bos, reason=reason)


def test_no_setup_when_h1_has_no_directional_bias(monkeypatch):
    _patch_structure(monkeypatch, _sr("RANGING"), _sr("RANGING"), _sr("RANGING"), _sr("RANGING"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "NO SETUP"
    assert result.direction is None


def test_liquidity_sweep_alone_does_not_create_valid_setup(monkeypatch):
    """Explicit spec requirement: a sweep by itself must only be DEVELOPING."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("RANGING"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "DEVELOPING"
    assert result.direction == "BUY"
    assert result.checklist["Liquidity Sweep"] is True
    assert result.checklist["MSS"] is False
    assert result.checklist["Displacement"] is False


def test_mss_alone_does_not_create_valid_setup(monkeypatch):
    """Explicit spec requirement: MSS by itself (no sweep, no displacement)
    is never VALID. Since Stage 23A the M5 sequence starts at the sweep, so
    an M5 shift with no qualifying sweep behind it isn't a checklist step at
    all: NO SETUP, MSS unchecked."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))  # no zones -> no sweep possible
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "NO SETUP"
    assert result.checklist["MSS"] is False
    assert result.checklist["Liquidity Sweep"] is False
    assert result.state != "VALID"


def test_full_checklist_with_valid_retracement_is_valid(monkeypatch):
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value="bullish"))
    _patch_sequence(monkeypatch, **ALL_STEPS)

    candles = _dummy_candles()
    result = setup_mod.detect_setup(candles, now=_fresh_now(candles))
    assert result.state == "VALID"
    assert result.direction == "BUY"
    assert all(result.checklist.values())
    assert result.entry_zone is not None
    assert result.stop_loss is not None
    assert result.rr is not None


def test_full_checklist_awaiting_retracement_is_developing_not_valid(monkeypatch):
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value="bullish"))
    _patch_sequence(monkeypatch, **{**ALL_STEPS, "retracement_ok": False})

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "DEVELOPING"
    assert "Waiting for retracement" in result.reason


def test_sweep_far_from_any_zone_does_not_count_as_confirmed(monkeypatch):
    """A sweep exists but price is nowhere near the swept zone anymore ->
    Liquidity Sweep checklist item must not be confirmed."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("RANGING"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 50.0}))  # far away
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=50.0, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["Liquidity Sweep"] is False


# ---------------------------------------------------------------------------
# Invalidation (spec section 15: "Ensure invalidation correctly cancels a
# setup") — see BUG-1 in the final report: as originally implemented this
# path was unreachable dead code.
# ---------------------------------------------------------------------------

def test_analyze_structure_never_pairs_opposite_hard_state_with_matching_last_mss():
    """Documents the invariant in the REAL structure engine that made the
    original invalidation gate (`checklist["MSS"] and m5.state == opposite`)
    impossible to satisfy: last_mss is only ever set together with
    state == "PULLBACK", never together with the opposite hard state."""
    from tests.test_structure import _ramp_path, _flat_candles_from_path, BULLISH_POINTS, BEARISH_POINTS

    bullish_break = _flat_candles_from_path(_ramp_path(BULLISH_POINTS[:6], steps_per_leg=7), tail=[104, 102, 100])
    r1 = real_analyze_structure(bullish_break)
    assert r1.last_mss == "bearish" and r1.state == "PULLBACK"  # never state == "BEARISH"

    bearish_break = _flat_candles_from_path(_ramp_path(BEARISH_POINTS[:6], steps_per_leg=7), tail=[96, 97, 98])
    r2 = real_analyze_structure(bearish_break)
    assert r2.last_mss == "bullish" and r2.state == "PULLBACK"  # never state == "BULLISH"


def test_invalidated_when_sweep_confirmed_and_m5_reverses_against_direction(monkeypatch):
    """Once the sweep and MSS have fired, M5 closing back beyond the swept
    extreme must cancel the setup."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("BEARISH"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))
    _patch_sequence(monkeypatch, sweep_index=5, mss_index=7, invalidated=True,
                    invalidation_reason="M5 closed back below the swept low (99.00) after the market structure shift.")

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "INVALIDATED"
    assert result.direction == "BUY"
    assert "swept low" in result.reason


def test_bearish_m5_precursor_after_a_low_sweep_is_not_invalidation(monkeypatch):
    """VAL-008 regression: right after a low sweep and before the bullish
    MSS, M5 is naturally BEARISH. The old check (`m5.state == "BEARISH"`)
    marked this fresh BUY candidate INVALIDATED. Real evaluate_sequence here."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("BEARISH"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "DEVELOPING"
    assert result.checklist["Liquidity Sweep"] is True


def test_not_invalidated_when_no_sweep_has_fired_yet(monkeypatch):
    """M5 merely being counter-trend before anything has been confirmed is
    normal pre-setup noise, not an invalidation — it should stay NO SETUP /
    DEVELOPING, never INVALIDATED."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("BEARISH"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))  # nothing to sweep
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state != "INVALIDATED"


def test_valid_setup_never_has_zero_or_negative_risk(monkeypatch):
    """_plan_trade's stop loss is the 10-bar extreme; if the current close
    happens to equal that extreme exactly, risk collapses to zero and R:R
    becomes undefined. A setup must never be promoted to VALID with a
    degenerate (zero-distance) stop."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value="bullish"))
    _patch_sequence(monkeypatch, **ALL_STEPS)

    candles = _dummy_candles()
    # Make the last close equal the 10-bar low exactly (a bar that closes on its own low).
    rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(14)]
    rows.append((100.0, 100.0, 98.0, 98.0))  # last bar: close == low == the window minimum
    candles["M5"] = make_candles(rows)

    result = setup_mod.detect_setup(candles, now=_fresh_now(candles))
    assert result.state != "VALID", "a zero-risk stop must never be promoted to a VALID setup"
    if result.rr is not None:
        assert result.rr > 0


# ---------------------------------------------------------------------------
# MSS semantics (established trend != an actual structure-shift event)
# ---------------------------------------------------------------------------

def test_mss_case_a_established_bullish_trend_without_shift_is_not_confirmed(monkeypatch):
    """M5 already agreeing with the trend (state=BULLISH, no last_mss) must
    NOT satisfy the MSS checklist item — that's alignment, not a shift."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH", last_mss=None))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is False


def test_mss_case_b_actual_bullish_shift_is_confirmed(monkeypatch):
    """A real shift, tied to a bar after the sweep (the sequence's
    mss_index), must satisfy MSS."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))
    _patch_sequence(monkeypatch, sweep_index=5, mss_index=7)

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is True


def test_mss_case_d_current_close_beyond_swing_without_a_shift_bar_is_not_confirmed(monkeypatch):
    """VAL-018: m5.last_mss only says "the latest close is beyond a swing"
    (no recency). Without a shift bar after the sweep, it is not the MSS step."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))
    _patch_sequence(monkeypatch, sweep_index=5)

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is False


def test_mss_case_c_established_bearish_trend_without_shift_is_not_confirmed(monkeypatch):
    _patch_structure(monkeypatch, _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH", last_mss=None))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is False


def test_mss_case_c_actual_bearish_shift_is_confirmed(monkeypatch):
    _patch_structure(monkeypatch, _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH"), _sr("PULLBACK", last_mss="bearish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing High": 101.5}))
    sweep = LiquidityEvent(time=None, label="H1 Swing High swept", level_name="H1 Swing High",
                            level_price=101.5, kind="sweep_high")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))
    _patch_sequence(monkeypatch, sweep_index=5, mss_index=7)

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is True


# ---------------------------------------------------------------------------
# Equal-level liquidity exposed through the setup context (not a checklist item)
# ---------------------------------------------------------------------------

def test_equal_levels_are_surfaced_in_market_analysis_context_when_present(monkeypatch):
    _patch_structure(monkeypatch, _sr("RANGING"), _sr("RANGING"), _sr("RANGING"), _sr("RANGING"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))
    equal_event = LiquidityEvent(time=None, label="Equal highs detected", level_name="Equal Highs",
                                  level_price=101.0, kind="equal_high")
    monkeypatch.setattr(setup_mod, "detect_equal_levels", Mock(return_value=[equal_event]))

    result = setup_mod.detect_setup(_dummy_candles())
    assert "Equal highs detected" in result.context["equal_levels"]


def test_equal_levels_never_gate_the_checklist():
    """Equal-level detection exposes information only — it must never appear
    as a checklist requirement (the strategy is unchanged by exposing it)."""
    assert "Equal Highs" not in setup_mod.CHECKLIST_STEPS
    assert "Equal Lows" not in setup_mod.CHECKLIST_STEPS
    assert setup_mod.CHECKLIST_STEPS == ["Liquidity Sweep", "MSS", "Displacement", "Retracement"]


def test_sell_setup_invalidated_on_bullish_m5_reversal_after_sweep(monkeypatch):
    _patch_structure(monkeypatch, _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH"), _sr("BULLISH"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing High": 100.1}))
    sweep = LiquidityEvent(time=None, label="H1 Swing High swept", level_name="H1 Swing High",
                            level_price=100.1, kind="sweep_high")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))
    _patch_sequence(monkeypatch, sweep_index=5, mss_index=7, invalidated=True,
                    invalidation_reason="M5 closed back above the swept high (100.50) after the market structure shift.")

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "INVALIDATED"
    assert result.direction == "SELL"


# ---------------------------------------------------------------------------
# Stage 21 (VAL-006): forming-candle exclusion in detect_setup() itself.
# ---------------------------------------------------------------------------

def _candles_with_one_forming_row(closed_rows, forming_row):
    """Builds an M5 DataFrame where every row in `closed_rows` is CLOSED
    and exactly one more `forming_row` at the end is still FORMING,
    relative to an explicit, controlled `now` -- never real wall-clock
    timing (see tests/conftest.py::make_candles' `now` param, added in
    Stage 21)."""
    rows = list(closed_rows) + [forming_row]
    start = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    now = start + timedelta(minutes=5 * (len(rows) - 1))  # exactly the last row is forming
    return make_candles(rows, start=start, now=now)


def test_detect_setup_passes_closed_only_candles_to_sweep_and_displacement_checks(monkeypatch):
    """Sweep and displacement confirmation must never see the forming
    candle -- verified by capturing exactly what DataFrame each function
    actually received."""
    closed_rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(14)]
    forming_row = (200.0, 210.0, 190.0, 205.0)  # wildly different -- easy to detect if it leaked through
    m5_df = _candles_with_one_forming_row(closed_rows, forming_row)

    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("RANGING"))
    sweeps_mock = Mock(return_value=[])
    displacement_mock = Mock(return_value=None)
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", sweeps_mock)
    monkeypatch.setattr(setup_mod, "detect_displacement", displacement_mock)
    sequence_mock = _patch_sequence(monkeypatch)

    other_df = make_candles([(100, 100.3, 99.7, 100.1)] * 20)
    setup_mod.detect_setup({"H4": other_df, "H1": other_df, "M15": other_df, "M5": m5_df})
    sequence_call_df = sequence_mock.call_args[0][0]
    assert len(sequence_call_df) == len(closed_rows)
    assert 200.0 not in sequence_call_df["open"].values

    sweeps_call_df = sweeps_mock.call_args[0][0]
    displacement_call_df = displacement_mock.call_args[0][0]
    assert len(sweeps_call_df) == len(closed_rows)
    assert len(displacement_call_df) == len(closed_rows)
    assert 200.0 not in sweeps_call_df["open"].values
    assert 200.0 not in displacement_call_df["open"].values


def test_detect_setup_zone_proximity_still_reflects_the_forming_candles_current_price(monkeypatch):
    """The legitimate exception (Stage 21): current-price context (zone
    proximity for the Liquidity Sweep checklist item) must still reflect
    the forming candle's close, not lag behind it."""
    closed_rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(14)]
    forming_row = (204.0, 206.0, 203.0, 205.0)  # current price ~205, far from the closed rows' ~101
    m5_df = _candles_with_one_forming_row(closed_rows, forming_row)

    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("RANGING"))
    # A zone sitting exactly at the FORMING candle's current price -- only
    # "near" if current_price correctly reads 205, not the closed set's ~101.4.
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 205.0}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=205.0, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    other_df = make_candles([(100, 100.3, 99.7, 100.1)] * 20)
    result = setup_mod.detect_setup({"H4": other_df, "H1": other_df, "M15": other_df, "M5": m5_df})

    assert result.checklist["Liquidity Sweep"] is True


# ---------------------------------------------------------------------------
# Stage 23A: the full sequence across bars (VAL-009) and staleness (VAL-011)
# ---------------------------------------------------------------------------

def _sequence_candles():
    from tests.test_sequence import FULL, SWEEP_IDX
    m5 = make_candles(FULL)
    other = make_candles([(100, 100.3, 99.7, 100.1)] * 20)
    sweep = LiquidityEvent(m5["time"].iloc[SWEEP_IDX], "Asian Low swept", "Asian Low", 98.8, "sweep_low")
    return {"H4": other, "H1": other, "M15": other, "M5": m5}, sweep


def test_sequence_spread_over_separate_bars_reaches_valid(monkeypatch):
    """VAL-009 end to end, with the REAL evaluate_sequence: sweep (bar 30),
    MSS + displacement (bar 32) and retracement (bar 34) are separate bars.
    Before Stage 23A this could never be VALID (all three were read off bar 34)."""
    candles, sweep = _sequence_candles()
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"Asian Low": 98.8}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))

    result = setup_mod.detect_setup(candles, now=_fresh_now(candles))
    assert result.state == "VALID", result.reason
    assert all(result.checklist.values())
    assert result.context["displacement"] is None  # the latest bar alone shows no displacement
    assert result.context["data_stale"] is False


def test_stale_feed_never_reports_valid(monkeypatch):
    """VAL-011: the same fully confirmed sequence, but no new M5 candle for
    an hour (frozen feed / outage / weekend) — DEVELOPING, flagged stale."""
    candles, sweep = _sequence_candles()
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"Asian Low": 98.8}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))

    stale_now = _fresh_now(candles) + timedelta(hours=1)
    result = setup_mod.detect_setup(candles, now=stale_now)
    assert result.state == "DEVELOPING"
    assert "stale" in result.reason
    assert result.context["data_stale"] is True
    assert result.stop_loss is None and result.rr is None
