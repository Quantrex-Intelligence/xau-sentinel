"""FundedNext risk monitor tests (Stage 2). Covers: daily loss calculation,
maximum drawdown, remaining loss, warning/critical/breached thresholds,
balance/equity changes, missing data, mock mode, live/disconnected mode,
boundary conditions, and day-reset (timezone) behavior.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import config
from mt5 import account as mt5_account
from risk import day_tracker, settings_store
from risk.fundednext import compute_status
from risk.models import AccountSnapshot, AccountType, Phase, SafetyLevel
from risk.rules import RULES


@pytest.fixture(autouse=True)
def _fixed_thresholds(monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_WARNING_THRESHOLD_PCT", 0.5)
    monkeypatch.setattr(config, "FUNDEDNEXT_CRITICAL_THRESHOLD_PCT", 0.8)
    monkeypatch.setattr(config, "FUNDEDNEXT_BALANCE_MISMATCH_TOLERANCE_PCT", 0.5)
    monkeypatch.setattr(config, "ACCOUNT_BALANCE", 100_000.0)


def _mock_snapshot(monkeypatch, balance, equity, source="mock"):
    monkeypatch.setattr(mt5_account, "get_account_snapshot",
                         Mock(return_value=AccountSnapshot(balance=balance, equity=equity, source=source)))


def _mock_history(monkeypatch, history):
    monkeypatch.setattr(mt5_account, "get_daily_pnl_history", Mock(return_value=history))


def _fixed_server_date(monkeypatch, d: date):
    from datetime import datetime
    monkeypatch.setattr(mt5_account, "server_now", Mock(return_value=datetime(d.year, d.month, d.day, 12, 0)))


# ---------------------------------------------------------------------------
# Rules sanity (guards against accidental edits to researched values)
# ---------------------------------------------------------------------------

def test_verified_rules_match_researched_values():
    r2 = RULES[AccountType.STELLAR_2STEP]
    assert (r2.daily_loss_pct, r2.max_loss_pct, r2.min_trading_days) == (0.05, 0.10, 5)
    assert (r2.profit_target_phase1_pct, r2.profit_target_phase2_pct) == (0.08, 0.05)
    assert r2.consistency_pct is None  # no consistency rule by default (opt-in add-on only)

    lite = RULES[AccountType.STELLAR_LITE]
    assert (lite.daily_loss_pct, lite.max_loss_pct, lite.min_trading_days) == (0.04, 0.08, 5)
    assert (lite.profit_target_phase1_pct, lite.profit_target_phase2_pct) == (0.08, 0.04)


# ---------------------------------------------------------------------------
# Daily loss calculation
# ---------------------------------------------------------------------------

def test_daily_loss_floor_and_remaining(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)  # fresh day, no P/L yet
    _mock_history(monkeypatch, [])

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    # daily_loss_pct=5% of 100k = 5000; floor = day_start(100000) - 5000 = 95000
    assert status.daily_loss_floor == 95_000.0
    assert status.daily_loss_remaining == 5_000.0
    assert status.daily_loss_used_pct == 0.0


def test_daily_loss_remaining_shrinks_with_floating_loss(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=97_500)  # 2500 floating loss today
    _mock_history(monkeypatch, [])

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.daily_loss_remaining == 2_500.0  # 5000 allowance - 2500 used
    assert status.daily_loss_used_pct == 50.0


# ---------------------------------------------------------------------------
# Maximum drawdown (static floor from initial balance)
# ---------------------------------------------------------------------------

def test_max_drawdown_floor_is_static_from_initial_balance_not_day_start(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    # day_start_balance will differ from initial_balance (account has grown over time)
    _mock_snapshot(monkeypatch, balance=108_000, equity=108_000)
    _mock_history(monkeypatch, [])

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    # max_loss_pct=10% of 100k initial = 10000; floor = 100000 - 10000 = 90000 (NOT day-start-relative)
    assert status.max_loss_floor == 90_000.0
    assert status.max_drawdown_remaining == 18_000.0


def test_max_drawdown_buffer_grows_with_profit(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    _mock_history(monkeypatch, [])
    baseline = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)

    _mock_snapshot(monkeypatch, balance=105_000, equity=105_000)
    grown = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)

    assert grown.max_loss_floor == baseline.max_loss_floor  # floor never moves
    assert grown.max_drawdown_remaining > baseline.max_drawdown_remaining  # buffer grows


# ---------------------------------------------------------------------------
# Safety levels: SAFE / WARNING / CRITICAL / BREACHED, with boundary conditions
# ---------------------------------------------------------------------------

def test_safety_level_safe_well_within_limits(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=99_800)  # trivial loss
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.safety_level == SafetyLevel.SAFE
    assert status.violations == []


def test_safety_level_warning_exactly_at_threshold_boundary(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    # daily allowance = 5000; exactly 50% used (threshold) -> equity = 100000 - 2500
    _mock_snapshot(monkeypatch, balance=100_000, equity=97_500)
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.daily_loss_used_pct == 50.0
    assert status.safety_level == SafetyLevel.WARNING


def test_safety_level_critical_exactly_at_threshold_boundary(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    # 80% of the 5000 daily allowance used -> equity = 100000 - 4000
    _mock_snapshot(monkeypatch, balance=100_000, equity=96_000)
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.daily_loss_used_pct == 80.0
    assert status.safety_level == SafetyLevel.CRITICAL


def test_safety_level_breached_when_equity_at_daily_floor_exactly(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=95_000)  # exactly at the floor
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.daily_loss_remaining == 0.0
    assert status.safety_level == SafetyLevel.BREACHED
    assert any(v.rule == "Daily Loss Limit" and v.level == SafetyLevel.BREACHED for v in status.violations)


def test_safety_level_breached_when_equity_below_max_floor(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=89_000)  # below the static 90000 floor
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.safety_level == SafetyLevel.BREACHED
    assert any(v.rule == "Maximum Loss Limit" and v.level == SafetyLevel.BREACHED for v in status.violations)


def test_max_loss_breach_takes_priority_reflected_in_both_violations(monkeypatch):
    """A catastrophic single-day loss can breach both limits simultaneously
    — both violations must be reported, not just the first one found."""
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=85_000)
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.safety_level == SafetyLevel.BREACHED
    rules_violated = {v.rule for v in status.violations}
    assert rules_violated == {"Daily Loss Limit", "Maximum Loss Limit"}


# ---------------------------------------------------------------------------
# Missing data / live / disconnected mode — never fabricate a value
# ---------------------------------------------------------------------------

def test_missing_account_data_returns_unknown_not_fabricated(monkeypatch):
    monkeypatch.setattr(mt5_account, "get_account_snapshot", Mock(
        return_value=AccountSnapshot(balance=0, equity=0, source="live", available=False,
                                      error="MT5 not connected")
    ))
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.data_available is False
    assert status.safety_level == SafetyLevel.UNKNOWN
    assert status.balance is None and status.equity is None
    assert "not connected" in status.reason.lower()


def test_live_disconnected_mode_via_real_get_account_snapshot(monkeypatch):
    """Exercises mt5.account.get_account_snapshot's own live/disconnected
    branch (not mocked at the compute_status level) end to end."""
    from mt5 import connection
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(connection, "mt5", None)  # simulates package unavailable, same as market_data.py's pattern
    monkeypatch.setattr(mt5_account, "mt5", None)

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.data_available is False
    assert status.safety_level == SafetyLevel.UNKNOWN


def test_mismatched_account_balance_returns_unknown_not_fabricated(monkeypatch):
    """OP-002 (docs/validation/OPERATIONAL_ISSUES.md): a live check found the
    connected MT5 account's real balance ($100,000) didn't match the
    configured ACCOUNT_BALANCE ($50,000, a 2x mismatch) — before this fix,
    progress_to_target_pct silently read 1250%. Reproduces that exact
    real-world ratio."""
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    monkeypatch.setattr(config, "ACCOUNT_BALANCE", 50_000.0)
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000, source="live")

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)

    assert status.data_available is False
    assert status.safety_level == SafetyLevel.UNKNOWN
    assert "ACCOUNT_BALANCE" in status.reason
    assert status.progress_to_target_pct is None


def test_in_tolerance_balance_change_from_real_trading_is_not_flagged_as_mismatched(monkeypatch):
    """The new OP-002 check must not trip on a real trading swing — only on
    an account that plainly isn't the configured one."""
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=104_000, equity=104_000)  # ACCOUNT_BALANCE=100_000 (fixture), a 4% move
    _mock_history(monkeypatch, [])

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)

    assert status.data_available is True
    assert status.progress_to_target_pct == 50.0  # unchanged from the pre-existing behavior


# ---------------------------------------------------------------------------
# Mock mode determinism
# ---------------------------------------------------------------------------

def test_mock_mode_is_deterministic_within_the_same_day():
    snap1 = mt5_account._mock_account_snapshot()
    snap2 = mt5_account._mock_account_snapshot()
    assert snap1.balance == snap2.balance
    assert snap1.equity == snap2.equity
    assert snap1.source == "mock"


def test_mock_data_never_reports_as_live():
    snapshot = mt5_account._mock_account_snapshot()
    assert snapshot.source == "mock"
    assert snapshot.source != "live"


# ---------------------------------------------------------------------------
# Day-reset / timezone behavior
# ---------------------------------------------------------------------------

def test_day_tracker_keeps_same_anchor_within_the_same_day():
    d = date(2026, 1, 5)
    first = day_tracker.get_day_start_balance(d, 100_000.0)
    second = day_tracker.get_day_start_balance(d, 103_500.0)  # balance moved intraday
    assert first == 100_000.0
    assert second == 100_000.0  # anchor unchanged — same server-local day


def test_day_tracker_resets_anchor_on_new_day():
    day1 = date(2026, 1, 5)
    day2 = date(2026, 1, 6)
    day_tracker.get_day_start_balance(day1, 100_000.0)
    reset = day_tracker.get_day_start_balance(day2, 101_200.0)
    assert reset == 101_200.0  # new day -> new anchor at whatever balance is now


def test_server_timezone_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_SERVER_TIMEZONE", "UTC")
    assert mt5_account.server_timezone().key == "UTC"


# ---------------------------------------------------------------------------
# Consistency rule (opt-in only — never assumed active)
# ---------------------------------------------------------------------------

def test_consistency_rule_not_evaluated_when_disabled(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    _mock_history(monkeypatch, [(date(2026, 1, 1), 5000), (date(2026, 1, 2), 100)])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE, consistency_enabled=False)
    assert status.largest_day_pct_of_profit is None
    assert not any(v.rule == "Consistency Rule" for v in status.violations)


def test_consistency_rule_flags_violation_when_enabled_and_exceeded(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    # one day is 98% of total profit -> exceeds the 40% on-demand-addon limit
    _mock_history(monkeypatch, [(date(2026, 1, 1), 4900), (date(2026, 1, 2), 100)])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE, consistency_enabled=True)
    assert status.largest_day_pct_of_profit == 98.0
    assert any(v.rule == "Consistency Rule" for v in status.violations)


# ---------------------------------------------------------------------------
# Trading-days-completed / profit target
# ---------------------------------------------------------------------------

def test_trading_days_completed_counts_history_entries(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    _mock_history(monkeypatch, [(date(2026, 1, i), 10) for i in range(1, 4)])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.trading_days_completed == 3
    assert status.trading_days_required == 5


def test_funded_phase_has_no_profit_target_or_min_trading_days(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.FUNDED)
    assert status.profit_target is None
    assert status.trading_days_required is None


def test_progress_to_target_reflects_equity_gain_over_initial_balance(monkeypatch):
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=104_000, equity=104_000)  # +4000 of an 8000 (8%) target
    _mock_history(monkeypatch, [])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.profit_target == 8_000.0
    assert status.progress_to_target_pct == 50.0


# ---------------------------------------------------------------------------
# Stage 19 VAL-002 regression: the daily-loss anchor must be derived from
# today's realized P/L, not from "whatever balance the app first observes
# today" — a trade closed before the app's first check on a new day must
# not be silently absorbed into the anchor.
# ---------------------------------------------------------------------------

def test_daily_loss_anchor_accounts_for_a_loss_realized_before_the_first_check(monkeypatch):
    """A trade closed $2000 down before the app was ever opened today must
    still count against today's daily-loss allowance — the account's
    CURRENT balance already reflects that loss, so the anchor must be
    computed as balance-minus-todays-realized-pnl, not just "the balance
    we happen to see right now"."""
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    # Balance already down $2000 from a trade closed earlier today.
    _mock_snapshot(monkeypatch, balance=98_000, equity=98_000)
    _mock_history(monkeypatch, [(date(2026, 1, 5), -2_000.0)])

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    # day_start_balance = 98000 - (-2000) = 100000 (the TRUE anchor before today's loss)
    assert status.day_start_balance == 100_000.0
    # daily allowance 5% of 100k = 5000; 2000 of it already used = 40%
    assert status.daily_loss_used_pct == 40.0
    assert status.daily_loss_remaining == 3_000.0


def test_daily_loss_anchor_unaffected_by_a_prior_days_history(monkeypatch):
    """Only TODAY's entry in the history should affect the anchor — a
    loss/gain from a previous day must not leak into today's floor."""
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    _mock_history(monkeypatch, [(date(2026, 1, 4), -5_000.0)])  # yesterday's loss, not today's

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.day_start_balance == 100_000.0
    assert status.daily_loss_used_pct == 0.0


def test_status_is_unknown_when_realized_pnl_history_is_unavailable(monkeypatch):
    """Financial-safety-sensitive: if today's realized P/L can't be
    determined at all, the anchor can't be trusted — fail toward an
    explicit UNKNOWN rather than silently falling back to an
    unverified value."""
    _fixed_server_date(monkeypatch, date(2026, 1, 5))
    _mock_snapshot(monkeypatch, balance=100_000, equity=100_000)
    _mock_history(monkeypatch, None)  # a genuine fetch failure, distinct from an empty list

    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.data_available is False
    assert status.safety_level == SafetyLevel.UNKNOWN
    assert "anchor" in status.reason.lower()


# ---------------------------------------------------------------------------
# Stage 19 VAL-002/VAL-016 regression: get_daily_pnl_history() must exclude
# non-trade deals (deposits, balance adjustments) from realized P/L.
# ---------------------------------------------------------------------------

def test_get_daily_pnl_history_excludes_non_trade_deals(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(config, "IS_MOCK", False)

    class FakeDeal:
        def __init__(self, deal_type, profit, day_offset_seconds):
            self.type = deal_type
            self.profit = profit
            self.time = int(datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc).timestamp()) + day_offset_seconds

    class FakeMT5:
        DEAL_TYPE_BUY = 0
        DEAL_TYPE_SELL = 1
        DEAL_TYPE_BALANCE = 2

        def history_deals_get(self, from_dt, to_dt):
            return [
                FakeDeal(self.DEAL_TYPE_BUY, 500.0, 0),       # a real trade close -- must count
                FakeDeal(self.DEAL_TYPE_BALANCE, 50_000.0, 1),  # a deposit -- must NOT count
                FakeDeal(self.DEAL_TYPE_SELL, -100.0, 2),      # a real trade close -- must count
            ]

    monkeypatch.setattr(mt5_account, "mt5", FakeMT5())
    monkeypatch.setattr(mt5_account.connection, "is_connected", Mock(return_value=True))
    monkeypatch.setattr(config, "FUNDEDNEXT_SERVER_TIMEZONE", "UTC")

    history = mt5_account.get_daily_pnl_history(days=10)
    assert history is not None
    total_pnl = sum(pnl for _, pnl in history)
    assert total_pnl == 400.0  # 500 + (-100), the 50000 "deposit" excluded entirely
