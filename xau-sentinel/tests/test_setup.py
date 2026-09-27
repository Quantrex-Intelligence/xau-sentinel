"""Setup state machine validation (spec section 15).

Uses mocks for the four underlying analysis calls (analyze_structure,
detect_sweeps, detect_displacement, compute_zones) so each state-machine
transition can be tested in isolation, independent of whether the
lower-level analysis functions themselves are correct (those have their own
dedicated test files).
"""
from unittest.mock import Mock

import pytest

import analysis.setup as setup_mod
from analysis.structure import StructureResult, analyze_structure as real_analyze_structure
from analysis.liquidity import LiquidityEvent
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
    must only be DEVELOPING, never VALID."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))  # no zones -> no sweep possible
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "DEVELOPING"
    assert result.checklist["MSS"] is True
    assert result.checklist["Liquidity Sweep"] is False
    assert result.state != "VALID"


def test_full_checklist_with_valid_retracement_is_valid(monkeypatch):
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value="bullish"))
    monkeypatch.setattr(setup_mod, "_check_retracement", Mock(return_value=True))

    result = setup_mod.detect_setup(_dummy_candles())
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
    monkeypatch.setattr(setup_mod, "_check_retracement", Mock(return_value=False))

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
    """Once the sweep has fired, a firm M5 structure break against the trade
    direction must cancel the setup."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("BEARISH"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={"H1 Swing Low": 99.9}))
    sweep = LiquidityEvent(time=None, label="H1 Swing Low swept", level_name="H1 Swing Low",
                            level_price=99.9, kind="sweep_low")
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[sweep]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "INVALIDATED"
    assert result.direction == "BUY"


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
    monkeypatch.setattr(setup_mod, "_check_retracement", Mock(return_value=True))

    candles = _dummy_candles()
    # Make the last close equal the 10-bar low exactly (a bar that closes on its own low).
    rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(14)]
    rows.append((100.0, 100.0, 98.0, 98.0))  # last bar: close == low == the window minimum
    candles["M5"] = make_candles(rows)

    result = setup_mod.detect_setup(candles)
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
    """A real shift (state=PULLBACK, last_mss=bullish) must satisfy MSS."""
    _patch_structure(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is True


def test_mss_case_c_established_bearish_trend_without_shift_is_not_confirmed(monkeypatch):
    _patch_structure(monkeypatch, _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH", last_mss=None))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.checklist["MSS"] is False


def test_mss_case_c_actual_bearish_shift_is_confirmed(monkeypatch):
    _patch_structure(monkeypatch, _sr("BEARISH"), _sr("BEARISH"), _sr("BEARISH"), _sr("PULLBACK", last_mss="bearish"))
    monkeypatch.setattr(setup_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(setup_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(setup_mod, "detect_displacement", Mock(return_value=None))

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

    result = setup_mod.detect_setup(_dummy_candles())
    assert result.state == "INVALIDATED"
    assert result.direction == "SELL"
