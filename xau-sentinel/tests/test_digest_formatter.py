"""Tests for ai/digest/formatter.py — deterministic Telegram text only,
never computes anything, never phrases a comparison as "better"/"worse"."""
from datetime import date

from ai.digest.formatter import _format_period_range, format_digest_telegram
from ai.digest.models import DigestSummary, DigestType, PeriodComparison
from ai.strategy_analytics.models import OverviewMetrics
from ai.trade_review.models import BehavioralPattern, DeviationType, StrategyAlignment


def _overview(**overrides):
    defaults = dict(
        total_trades=8, wins=5, losses=2, breakeven=1, win_rate=62.5, total_r=2.4, avg_r=0.3,
        profit_factor=2.0, median_r=0.3, avg_holding_duration_minutes=40.0,
        strategy_alignment_counts={
            StrategyAlignment.ALIGNED: 6, StrategyAlignment.PARTIALLY_ALIGNED: 1,
            StrategyAlignment.NOT_ALIGNED: 1, StrategyAlignment.UNKNOWN: 0,
        },
        risk_alignment_counts={
            StrategyAlignment.ALIGNED: 7, StrategyAlignment.PARTIALLY_ALIGNED: 0,
            StrategyAlignment.NOT_ALIGNED: 1, StrategyAlignment.UNKNOWN: 0,
        },
    )
    defaults.update(overrides)
    return OverviewMetrics(**defaults)


def _summary(**overrides):
    defaults = dict(
        # Half-open: period_end is the first day of the NEXT period
        # (exclusive) -- Sep 21 (Mon) through Sep 27 (Sun) inclusive is
        # [2026-09-21, 2026-09-28).
        digest_type=DigestType.WEEKLY, period_start=date(2026, 9, 21), period_end=date(2026, 9, 28),
        generated_at="2026-09-28T00:00:00+00:00", overview=_overview(), behavioral_patterns=[],
        previous_period=None,
    )
    defaults.update(overrides)
    return DigestSummary(**defaults)


def test_header_names_the_digest_type():
    text = format_digest_telegram(_summary(digest_type=DigestType.WEEKLY))
    assert "Weekly Digest" in text
    text = format_digest_telegram(_summary(digest_type=DigestType.MONTHLY))
    assert "Monthly Digest" in text


def test_trading_section_renders_core_numbers():
    text = format_digest_telegram(_summary())
    assert "8 trades" in text
    assert "5W · 2L · 1BE" in text
    assert "+2.40R" in text
    assert "Avg R: +0.30" in text
    assert "Win rate: 62.5%" in text


def test_strategy_and_risk_sections_omit_zero_counts():
    text = format_digest_telegram(_summary())
    assert "Aligned: 6" in text
    assert "Partial: 1" in text
    assert "Not aligned: 1" in text
    assert "Unknown: 0" not in text
    assert "Aligned: 7" in text
    assert "Partial: 0" not in text


def test_behavior_section_lists_patterns_with_a_readable_label():
    patterns = [BehavioralPattern(
        deviation_type=DeviationType.INSUFFICIENT_RR, sample_count=3, total_relevant_trades=8,
        occurrence_rate=0.375, trades_with_loss=2, note="Observed historical association, not evidence of causation.",
    )]
    text = format_digest_telegram(_summary(behavioral_patterns=patterns))
    assert "Insufficient R:R" in text
    assert "3 occurrences" in text


def test_behavior_section_shows_exact_no_patterns_string_when_empty():
    text = format_digest_telegram(_summary(behavioral_patterns=[]))
    assert "No recurring behavioral patterns detected." in text


def test_previous_period_line_omitted_when_none():
    text = format_digest_telegram(_summary(previous_period=None))
    assert "PREVIOUS PERIOD" not in text


def test_previous_period_line_renders_when_present():
    comparison = PeriodComparison(
        current_trade_count=8, current_total_r=2.4, current_avg_r=0.3, current_win_rate=62.5,
        current_strategy_alignment_counts={StrategyAlignment.ALIGNED: 6},
        previous_trade_count=6, previous_total_r=1.1, previous_avg_r=0.18, previous_win_rate=50.0,
        previous_strategy_alignment_counts={StrategyAlignment.ALIGNED: 4},
    )
    text = format_digest_telegram(_summary(previous_period=comparison))
    assert "PREVIOUS PERIOD" in text
    assert "6 trades · +1.10R" in text


def test_negative_total_r_rendered_with_minus_sign_not_double_signed():
    text = format_digest_telegram(_summary(overview=_overview(total_r=-1.5, avg_r=-0.25)))
    assert "-1.50R" in text
    assert "Avg R: -0.25" in text


# ---------------------------------------------------------------------------
# Stage 20 VAL-004: the human-readable "Period" line must show the correct
# INCLUSIVE display range given the half-open (start, end) bounds
# build_digest() now produces internally.
# ---------------------------------------------------------------------------

def test_weekly_period_range_displays_the_inclusive_last_day():
    # Half-open [2026-09-21, 2026-09-28) -> displayed as "Sep 21-27".
    text = _format_period_range(DigestType.WEEKLY, date(2026, 9, 21), date(2026, 9, 28))
    assert text == "Sep 21–27"


def test_weekly_period_range_spanning_two_months_displays_both_month_names():
    # Half-open [2026-09-28, 2026-10-05) -> displayed as "Sep 28-Oct 04".
    text = _format_period_range(DigestType.WEEKLY, date(2026, 9, 28), date(2026, 10, 5))
    assert text == "Sep 28–Oct 04"


def test_monthly_period_range_shows_month_and_year_unaffected_by_end_semantics():
    # Half-open [2026-01-01, 2026-02-01) -> displayed as "January 2026".
    text = _format_period_range(DigestType.MONTHLY, date(2026, 1, 1), date(2026, 2, 1))
    assert text == "January 2026"


def test_full_digest_renders_the_inclusive_period_line():
    text = format_digest_telegram(_summary())
    assert "Sep 21–27" in text


def test_never_uses_comparative_or_predictive_language():
    comparison = PeriodComparison(
        current_trade_count=8, current_total_r=2.4, current_avg_r=0.3, current_win_rate=62.5,
        current_strategy_alignment_counts={StrategyAlignment.ALIGNED: 6},
        previous_trade_count=6, previous_total_r=1.1, previous_avg_r=0.18, previous_win_rate=50.0,
        previous_strategy_alignment_counts={StrategyAlignment.ALIGNED: 4},
    )
    patterns = [BehavioralPattern(
        deviation_type=DeviationType.DIRECTION_DEVIATION, sample_count=3, total_relevant_trades=8,
        occurrence_rate=0.375, trades_with_loss=2, note="Observed historical association, not evidence of causation.",
    )]
    text = format_digest_telegram(_summary(previous_period=comparison, behavioral_patterns=patterns)).lower()
    for banned in ("better", "worse", "improving", "deteriorating", "probability", "will win", "should", "recommend"):
        assert banned not in text
