"""Tests for ai/digest/service.py — period boundaries, period filtering,
and build_digest()'s pure delegation to ai.strategy_analytics.metrics and
ai.trade_review.patterns (never reimplemented, never touching a provider
or the store)."""
import inspect
from datetime import date

import pytest

from ai.digest import service
from ai.digest.models import DigestType
from ai.strategy_analytics import metrics as strategy_metrics
from ai.trade_review import patterns


def _trade(trade_id, trade_date, **overrides):
    defaults = dict(
        id=trade_id, status="CLOSED", result="WIN", direction="BUY", trade_date=trade_date,
        h1_bias="BULLISH", liquidity="Previous Day Low swept", mss="Bullish", displacement="Bullish",
        planned_rr=3.0, r_multiple=1.0, duration_minutes=30.0,
    )
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def _no_fundednext_snapshot(monkeypatch):
    """ai.strategy_analytics.metrics and ai.trade_review.patterns each hold
    their own module-level import of risk.fundednext_journal.get_snapshot
    -- both must be patched, or aggregate_patterns()'s per-trade lookup
    hits a real (uninitialized) DB table in this no-temp_db test file."""
    monkeypatch.setattr(strategy_metrics, "get_fundednext_snapshot", lambda trade_id: None)
    monkeypatch.setattr(patterns, "get_fundednext_snapshot", lambda trade_id: None)


# ---------------------------------------------------------------------------
# compute_period_bounds -- half-open [start, end); end is the first day of
# the NEXT period (exclusive), not the last day of this one.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reference,expected_start,expected_end", [
    (date(2026, 9, 29), date(2026, 9, 28), date(2026, 10, 5)),  # Tuesday
    (date(2026, 9, 28), date(2026, 9, 28), date(2026, 10, 5)),  # Monday itself
    (date(2026, 10, 4), date(2026, 9, 28), date(2026, 10, 5)),  # Sunday itself
])
def test_weekly_bounds_monday_to_next_monday(reference, expected_start, expected_end):
    start, end = service.compute_period_bounds(DigestType.WEEKLY, reference)
    assert (start, end) == (expected_start, expected_end)


def test_monthly_bounds_first_of_month_to_first_of_next_month():
    start, end = service.compute_period_bounds(DigestType.MONTHLY, date(2026, 2, 15))
    assert (start, end) == (date(2026, 2, 1), date(2026, 3, 1))


def test_previous_weekly_bounds_steps_back_one_week():
    prev_start, prev_end = service.previous_period_bounds(DigestType.WEEKLY, date(2026, 9, 28))
    assert (prev_start, prev_end) == (date(2026, 9, 21), date(2026, 9, 28))


def test_previous_monthly_bounds_crosses_year_boundary():
    prev_start, prev_end = service.previous_period_bounds(DigestType.MONTHLY, date(2026, 1, 1))
    assert (prev_start, prev_end) == (date(2025, 12, 1), date(2026, 1, 1))


# ---------------------------------------------------------------------------
# trades_in_period -- half-open: end (the next period's start) is excluded.
# ---------------------------------------------------------------------------

def test_trades_in_period_includes_start_excludes_end():
    trades = [_trade(1, "2026-09-28"), _trade(2, "2026-10-04"), _trade(3, "2026-09-27"), _trade(4, "2026-10-05")]
    result = service.trades_in_period(trades, date(2026, 9, 28), date(2026, 10, 5))
    assert {t["id"] for t in result} == {1, 2}


def test_trades_in_period_excludes_missing_or_malformed_trade_date():
    trades = [_trade(1, None), _trade(2, "not-a-date"), _trade(3, "2026-09-28")]
    result = service.trades_in_period(trades, date(2026, 9, 28), date(2026, 10, 5))
    assert {t["id"] for t in result} == {3}


# ---------------------------------------------------------------------------
# Stage 20 VAL-004 regression: build_digest() must report the last
# COMPLETED period, never the in-progress one containing `reference`.
# All using an explicit injected reference, never the real wall clock.
# ---------------------------------------------------------------------------

def test_weekly_digest_excludes_the_in_progress_week_and_includes_the_completed_one(monkeypatch):
    in_progress_week_trade = _trade(1, "2026-09-29")  # Tuesday, inside the current in-progress week
    completed_week_trade = _trade(2, "2026-09-24")  # last Thursday, inside the completed prior week
    monkeypatch.setattr(patterns, "closed_trades", lambda: [in_progress_week_trade, completed_week_trade])

    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    assert (summary.period_start, summary.period_end) == (date(2026, 9, 21), date(2026, 9, 28))
    assert summary.overview.total_trades == 1  # only the completed-week trade


def test_monthly_digest_excludes_the_in_progress_month_and_includes_the_completed_one(monkeypatch):
    in_progress_month_trade = _trade(1, "2026-02-05")  # inside the current in-progress month
    completed_month_trade = _trade(2, "2026-01-20")  # inside the completed prior month
    monkeypatch.setattr(patterns, "closed_trades", lambda: [in_progress_month_trade, completed_month_trade])

    summary = service.build_digest(DigestType.MONTHLY, reference=date(2026, 2, 1))
    assert (summary.period_start, summary.period_end) == (date(2026, 1, 1), date(2026, 2, 1))
    assert summary.overview.total_trades == 1


def test_weekly_digest_reference_on_sunday_reports_the_same_completed_week_as_monday(monkeypatch):
    monkeypatch.setattr(patterns, "closed_trades", lambda: [])
    monday_summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 28))
    sunday_summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 10, 4))
    assert (monday_summary.period_start, monday_summary.period_end) == \
           (sunday_summary.period_start, sunday_summary.period_end) == \
           (date(2026, 9, 21), date(2026, 9, 28))


def test_monthly_digest_handles_december_to_january_rollover(monkeypatch):
    monkeypatch.setattr(patterns, "closed_trades", lambda: [])
    summary = service.build_digest(DigestType.MONTHLY, reference=date(2027, 1, 1))
    assert (summary.period_start, summary.period_end) == (date(2026, 12, 1), date(2027, 1, 1))


def test_build_digest_respects_session_timezone_not_utc_for_the_default_reference(monkeypatch):
    """When no explicit reference is given, "today" must be computed in
    config.SESSION_TIMEZONE, not UTC -- a reference near local midnight in
    a timezone ahead of UTC can fall on a different calendar date than
    UTC's "now"."""
    monkeypatch.setattr("config.SESSION_TIMEZONE", "Asia/Tokyo")  # UTC+9, no DST
    from datetime import datetime, timezone as tz
    from zoneinfo import ZoneInfo
    # A UTC instant that is still 2026-09-28 in UTC but already 2026-09-29
    # (Tuesday) in Tokyo -- proves the anchor is the CONFIGURED zone's date.
    fixed_utc_instant = datetime(2026, 9, 28, 16, 30, tzinfo=tz.utc)
    monkeypatch.setattr(service, "_now", lambda: fixed_utc_instant.astimezone(ZoneInfo("Asia/Tokyo")))
    monkeypatch.setattr(patterns, "closed_trades", lambda: [])

    summary = service.build_digest(DigestType.WEEKLY)  # no reference -> uses service._now()
    # Tokyo date is 2026-09-29 (Tuesday) -> completed week is Sep 21-28.
    assert (summary.period_start, summary.period_end) == (date(2026, 9, 21), date(2026, 9, 28))


def test_previous_period_comparison_still_populates_one_period_further_back(monkeypatch):
    completed_week_trade = _trade(1, "2026-09-24")
    week_before_that_trade = _trade(2, "2026-09-17")
    monkeypatch.setattr(patterns, "closed_trades", lambda: [completed_week_trade, week_before_that_trade])

    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    assert summary.previous_period is not None
    assert summary.previous_period.current_trade_count == 1
    assert summary.previous_period.previous_trade_count == 1


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------

def test_build_digest_empty_period_has_zero_overview_and_no_previous_period(monkeypatch):
    monkeypatch.setattr(patterns, "closed_trades", lambda: [])
    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    assert summary.overview.total_trades == 0
    assert summary.behavioral_patterns == []
    assert summary.previous_period is None


def test_build_digest_overview_matches_strategy_metrics_directly(monkeypatch):
    # Reference is Tuesday 2026-09-29 -- the completed week it reports on
    # is 2026-09-21 (Mon) through 2026-09-27 (Sun).
    period_trades = [_trade(1, "2026-09-21"), _trade(2, "2026-09-24", result="LOSS", r_multiple=-1.0)]
    monkeypatch.setattr(patterns, "closed_trades", lambda: period_trades)
    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    expected = strategy_metrics.compute_overview(period_trades)
    assert summary.overview == expected


def test_build_digest_patterns_match_trade_review_patterns_directly(monkeypatch):
    period_trades = [_trade(i, "2026-09-21", h1_bias="BEARISH") for i in range(1, 4)]
    monkeypatch.setattr(patterns, "closed_trades", lambda: period_trades)
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 3)
    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    expected = patterns.aggregate_patterns(period_trades)
    assert summary.behavioral_patterns == expected
    assert len(summary.behavioral_patterns) > 0


def test_build_digest_previous_period_only_set_when_prior_data_exists(monkeypatch):
    # Reference Sep 29 -> completed (reported) week is Sep21-27; the
    # comparison's "previous period" is one week further back, Sep14-20.
    all_trades = [_trade(1, "2026-09-21"), _trade(2, "2026-09-14")]  # completed week + the week before it
    monkeypatch.setattr(patterns, "closed_trades", lambda: all_trades)
    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    assert summary.previous_period is not None
    assert summary.previous_period.previous_trade_count == 1
    assert summary.previous_period.current_trade_count == 1


def test_build_digest_dates_are_the_expected_completed_period(temp_db):
    # temp_db: build_digest() reads the trades table (Stage 23B fix; it
    # failed with "no such table: trades" on a fresh checkout).
    summary = service.build_digest(DigestType.WEEKLY, reference=date(2026, 9, 29))
    assert (summary.period_start, summary.period_end) == (date(2026, 9, 21), date(2026, 9, 28))


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

def test_build_digest_never_calls_a_provider_or_writes_to_the_store():
    source = inspect.getsource(service.build_digest)
    for banned in ("get_notification_provider", "provider.send", "record_sent", "store."):
        assert banned not in source


def test_service_module_never_reimplements_alignment_or_setup_rules():
    source = inspect.getsource(service)
    for banned in ("_h1_bias_consistency", "detect_setup", "_infer_liquidity_kind", "BULLISH", "BEARISH"):
        assert banned not in source
