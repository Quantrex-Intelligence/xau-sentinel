"""Tests for the FundedNext-in-journal snapshot storage (risk/fundednext_journal.py):
persistence, missing-data handling, and — the core requirement — that a
saved snapshot is immutable once written."""
import pytest

from journal.database import init_db
from journal import trades as trades_repo
from risk.fundednext_journal import get_snapshot, init_table, save_snapshot
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel


@pytest.fixture
def fn_journal_db(temp_db):
    """temp_db already isolates config.DB_PATH; this also creates the new
    fundednext_context table in that same isolated file."""
    init_db()
    init_table()
    return temp_db


def _trade_id(fn_journal_db) -> int:
    return trades_repo.create_trade(
        {"trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
         "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
         "take_profit": 110.0, "planned_rr": 2.0, "setup": None, "market_regime": None,
         "notes": None, "screenshot_path": None},
        {"h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
         "regime": "TRENDING UP", "liquidity": None, "mss": None, "displacement": None, "session": "London"},
    )


def _available_status(**overrides) -> FundedNextStatus:
    defaults = dict(
        account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock", data_available=True,
        balance=50_000.0, equity=50_100.0, today_pnl=100.0, daily_loss_remaining=2_600.0,
        daily_loss_used_pct=0.0, max_drawdown_remaining=5_100.0, max_drawdown_used_pct=0.0,
        safety_level=SafetyLevel.SAFE, reason="All FundedNext limits within safe range.",
    )
    defaults.update(overrides)
    return FundedNextStatus(**defaults)


def test_snapshot_persists_and_is_retrievable(fn_journal_db):
    trade_id = _trade_id(fn_journal_db)
    save_snapshot(trade_id, _available_status(), rules_daily_loss_pct=0.05, rules_max_loss_pct=0.10)

    saved = get_snapshot(trade_id)
    assert saved is not None
    assert saved["data_available"] == 1
    assert saved["account_type"] == "stellar_2step"
    assert saved["balance"] == 50_000.0
    assert saved["equity"] == 50_100.0
    assert saved["daily_loss_pct_rule"] == 0.05
    assert saved["max_loss_pct_rule"] == 0.10
    assert saved["safety_level"] == "SAFE"


def test_missing_fundednext_data_stored_as_explicit_unavailable(fn_journal_db):
    trade_id = _trade_id(fn_journal_db)
    unavailable = FundedNextStatus(
        account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="live", data_available=False,
        safety_level=SafetyLevel.UNKNOWN, reason="MT5 not connected",
    )
    save_snapshot(trade_id, unavailable, rules_daily_loss_pct=None, rules_max_loss_pct=None)

    saved = get_snapshot(trade_id)
    assert saved["data_available"] == 0
    assert saved["safety_level"] == "UNKNOWN"
    assert saved["balance"] is None  # never fabricated
    assert saved["equity"] is None
    assert "not connected" in saved["reason"].lower()


def test_mock_mode_recorded_on_snapshot(fn_journal_db):
    trade_id = _trade_id(fn_journal_db)
    save_snapshot(trade_id, _available_status(mode="mock"), rules_daily_loss_pct=0.05, rules_max_loss_pct=0.10)
    assert get_snapshot(trade_id)["mode"] == "mock"


def test_live_mode_recorded_on_snapshot(fn_journal_db):
    trade_id = _trade_id(fn_journal_db)
    save_snapshot(trade_id, _available_status(mode="live"), rules_daily_loss_pct=0.05, rules_max_loss_pct=0.10)
    assert get_snapshot(trade_id)["mode"] == "live"


def test_no_snapshot_returns_none_not_a_crash(fn_journal_db):
    trade_id = _trade_id(fn_journal_db)
    assert get_snapshot(trade_id) is None


def test_historical_snapshot_is_immutable_after_later_writes(fn_journal_db):
    """The core requirement: capturing a snapshot for a LATER trade, with
    different account figures, must never alter an EARLIER trade's already-
    saved context."""
    trade1 = _trade_id(fn_journal_db)
    save_snapshot(trade1, _available_status(balance=50_000.0, equity=50_100.0), 0.05, 0.10)
    original = get_snapshot(trade1)

    trade2 = _trade_id(fn_journal_db)
    save_snapshot(trade2, _available_status(
        account_type=AccountType.STELLAR_LITE, balance=61_000.0, equity=60_500.0,
        safety_level=SafetyLevel.WARNING, reason="80% of daily loss used.",
    ), 0.04, 0.08)

    trade1_again = get_snapshot(trade1)
    assert trade1_again == original
    assert trade1_again["balance"] == 50_000.0
    assert trade1_again["account_type"] == "stellar_2step"
    assert trade1_again["safety_level"] == "SAFE"

    trade2_snapshot = get_snapshot(trade2)
    assert trade2_snapshot["balance"] == 61_000.0
    assert trade2_snapshot["account_type"] == "stellar_lite"
