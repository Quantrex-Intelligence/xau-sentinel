"""Unit tests for every pure rule function in ai/strategy/rules.py — one
test (or BUY/SELL pair) per numbered item in the locked Stage 4
specification, independent of the orchestration in evaluator.py."""
from datetime import datetime, timedelta, timezone

import pytest

import config
from ai.strategy import rules
from analysis.liquidity import LiquidityEvent
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _sweep(kind, minutes_ago=0, level_name="Previous Day Low", level_price=99.0, label=None):
    return LiquidityEvent(
        time=NOW - timedelta(minutes=minutes_ago), label=label or f"{level_name} swept",
        level_name=level_name, level_price=level_price, kind=kind,
    )


# --- item 3 / item 7: candidate selection ---------------------------------

def test_select_candidate_none_when_no_sweeps():
    assert rules.select_candidate([]) is None


def test_select_candidate_picks_most_recent_of_either_kind():
    older = _sweep("sweep_low", minutes_ago=30)
    newer = _sweep("sweep_high", minutes_ago=5, level_name="Asian High")
    assert rules.select_candidate([older, newer]) is newer


@pytest.mark.parametrize("kind,expected", [("sweep_low", "BUY"), ("sweep_high", "SELL")])
def test_candidate_direction_symmetry(kind, expected):
    assert rules.candidate_direction(_sweep(kind)) == expected


# --- item 10 / item 7: sweep recency window --------------------------------

def test_within_sweep_window_true_for_recent_sweep():
    assert rules.is_within_sweep_window(NOW - timedelta(minutes=30), NOW, window_minutes=60) is True


def test_within_sweep_window_false_once_expired():
    assert rules.is_within_sweep_window(NOW - timedelta(minutes=61), NOW, window_minutes=60) is False


def test_within_sweep_window_boundary_is_inclusive():
    assert rules.is_within_sweep_window(NOW - timedelta(minutes=60), NOW, window_minutes=60) is True


# --- item 10: opposing M5 MSS invalidation, BUY/SELL symmetry -------------

@pytest.mark.parametrize("direction,m5_state,expected", [
    ("BUY", "BEARISH", True), ("BUY", "BULLISH", False), ("BUY", "RANGING", False),
    ("SELL", "BULLISH", True), ("SELL", "BEARISH", False), ("SELL", "RANGING", False),
])
def test_opposing_mss_invalidation_symmetry(direction, m5_state, expected):
    assert rules.is_opposing_mss_invalidated(direction, m5_state) is expected


# --- item 10: H1 flip invalidation, BUY/SELL symmetry ----------------------

@pytest.mark.parametrize("direction,h1_state,expected", [
    ("BUY", "BEARISH", True), ("BUY", "RANGING", False), ("BUY", "PULLBACK", False),
    ("SELL", "BULLISH", True), ("SELL", "RANGING", False), ("SELL", "PULLBACK", False),
])
def test_h1_flip_invalidation_symmetry(direction, h1_state, expected):
    """RANGING/PULLBACK are "not yet confirming," not a flip — only the hard
    opposite state counts, per the locked interpretation."""
    assert rules.is_h1_flip_invalidated(direction, h1_state) is expected


# --- item 1 / item 2: H1 gate, BUY/SELL symmetry ---------------------------

@pytest.mark.parametrize("direction,state,mss,expected", [
    ("BUY", "BULLISH", None, True),
    ("BUY", "PULLBACK", "bullish", True),
    ("BUY", "PULLBACK", "bearish", False),  # H1 itself mid-bearish-shift -> does not support BUY
    ("BUY", "BEARISH", None, False),
    ("SELL", "BEARISH", None, True),
    ("SELL", "PULLBACK", "bearish", True),
    ("SELL", "PULLBACK", "bullish", False),
    ("SELL", "BULLISH", None, False),
])
def test_h1_supports_direction_symmetry(direction, state, mss, expected):
    assert rules.h1_supports_direction(direction, state, mss) is expected


# --- item 5: M5 MSS, BUY/SELL symmetry, established-trend vs actual shift -

@pytest.mark.parametrize("direction,last_mss,expected", [
    ("BUY", "bullish", True), ("BUY", None, False), ("BUY", "bearish", False),
    ("SELL", "bearish", True), ("SELL", None, False), ("SELL", "bullish", False),
])
def test_m5_mss_confirmation_symmetry(direction, last_mss, expected):
    assert rules.is_m5_mss_confirmed(direction, last_mss) is expected


# --- item 6: displacement, BUY/SELL symmetry -------------------------------

@pytest.mark.parametrize("direction,displacement,expected", [
    ("BUY", "bullish", True), ("BUY", "bearish", False), ("BUY", None, False),
    ("SELL", "bearish", True), ("SELL", "bullish", False), ("SELL", None, False),
])
def test_displacement_confirmation_symmetry(direction, displacement, expected):
    assert rules.is_displacement_confirmed(direction, displacement) is expected


# --- item 8: stop loss, BUY/SELL symmetry ----------------------------------

def test_stop_loss_buy_is_below_swept_low_by_buffer():
    assert rules.compute_stop_loss("BUY", 3700.00, buffer=0.30) == 3699.70


def test_stop_loss_sell_is_above_swept_high_by_buffer():
    assert rules.compute_stop_loss("SELL", 3700.00, buffer=0.30) == 3700.30


def test_stop_loss_uses_configured_default_buffer(monkeypatch):
    monkeypatch.setattr(config, "AI_STRATEGY_SL_BUFFER", 0.50)
    assert rules.compute_stop_loss("BUY", 100.0) == 99.50


# --- item 9: target selection, BUY/SELL symmetry ---------------------------

def test_select_target_buy_picks_nearest_qualifying_high_above_entry():
    zones = {"Previous Day High": 3720.0, "Asian High": 3710.0, "H4 Swing High": 3750.0}
    assert rules.select_target("BUY", zones, entry=3705.0) == 3710.0


def test_select_target_sell_picks_nearest_qualifying_low_below_entry():
    zones = {"Previous Day Low": 3680.0, "Asian Low": 3690.0, "H4 Swing Low": 3650.0}
    assert rules.select_target("SELL", zones, entry=3695.0) == 3690.0


def test_select_target_ignores_non_qualifying_zone_names():
    """VWAP and Current Day High/Low are not in Stage 1's qualifying-liquidity
    lists (analysis/liquidity.py) and must never be used as an A+ target."""
    zones = {"VWAP": 3706.0, "Current Day High": 3707.0, "Previous Day High": 3720.0}
    assert rules.select_target("BUY", zones, entry=3705.0) == 3720.0


def test_select_target_none_when_nothing_qualifies_beyond_entry():
    zones = {"Previous Day High": 3700.0}  # below entry, not a valid BUY target
    assert rules.select_target("BUY", zones, entry=3705.0) is None


# --- item 9: risk:reward -----------------------------------------------------

def test_risk_reward_matches_expected_ratio():
    rr, risk, reward = rules.compute_risk_reward("BUY", entry=100.0, stop_loss=99.0, target=103.0)
    assert risk == 1.0
    assert reward == 3.0
    assert rr == 3.0


def test_risk_reward_none_when_no_target():
    rr, risk, reward = rules.compute_risk_reward("BUY", entry=100.0, stop_loss=99.0, target=None)
    assert rr is None and reward is None
    assert risk == 1.0


def test_risk_reward_none_on_degenerate_zero_risk_stop():
    rr, risk, reward = rules.compute_risk_reward("BUY", entry=100.0, stop_loss=100.0, target=103.0)
    assert rr is None


def test_passes_min_rr_boundary_inclusive():
    assert rules.passes_min_rr(3.0, min_rr=3.0) is True


def test_passes_min_rr_just_below_fails():
    assert rules.passes_min_rr(2.99, min_rr=3.0) is False


def test_passes_min_rr_none_fails():
    assert rules.passes_min_rr(None) is False


# --- item 11: FundedNext gate -----------------------------------------------

def _status(**overrides):
    defaults = dict(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                     data_available=True, safety_level=SafetyLevel.SAFE, daily_loss_used_pct=10.0,
                     reason="All FundedNext limits within safe range.")
    defaults.update(overrides)
    return FundedNextStatus(**defaults)


def test_fundednext_gate_passes_when_safe_and_under_threshold():
    ok, _ = rules.check_fundednext_gate(_status(daily_loss_used_pct=10.0), max_daily_loss_used_pct=50.0)
    assert ok is True


def test_fundednext_gate_fails_when_not_safe():
    ok, reason = rules.check_fundednext_gate(_status(safety_level=SafetyLevel.WARNING), max_daily_loss_used_pct=50.0)
    assert ok is False
    assert "not SAFE" in reason


def test_fundednext_gate_fails_at_threshold_boundary():
    """Locked spec: "below 50%" — exactly 50% must NOT pass."""
    ok, _ = rules.check_fundednext_gate(_status(daily_loss_used_pct=50.0), max_daily_loss_used_pct=50.0)
    assert ok is False


def test_fundednext_gate_fails_just_under_boundary_passes():
    ok, _ = rules.check_fundednext_gate(_status(daily_loss_used_pct=49.9), max_daily_loss_used_pct=50.0)
    assert ok is True


def test_fundednext_gate_fails_when_data_unavailable():
    ok, reason = rules.check_fundednext_gate(
        FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="live",
                          data_available=False, safety_level=SafetyLevel.UNKNOWN, reason="MT5 not connected"),
        max_daily_loss_used_pct=50.0,
    )
    assert ok is False
    assert "unavailable" in reason.lower()
