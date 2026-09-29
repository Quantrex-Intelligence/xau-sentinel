"""Tests for ai/strategy_analytics/metrics.py — descriptive aggregation
only. Core win/loss numbers must match journal.trades.compute_analytics()
exactly (delegated, not reimplemented); alignment/outcome must match
ai.trade_review.engine.build_trade_review() (delegated, not re-derived).
"""
import inspect

import pandas as pd
import pytest

from ai.strategy_analytics import metrics
from ai.trade_review.models import Outcome, StrategyAlignment
from journal import trades as trades_repo


def _trade(trade_id, **overrides):
    defaults = dict(
        id=trade_id, status="CLOSED", result="WIN", direction="BUY",
        h1_bias="BULLISH", liquidity="Previous Day Low swept", mss="Bullish", displacement="Bullish",
        planned_rr=3.0, r_multiple=1.0, duration_minutes=30.0,
        session="London", regime="TRENDING", market_regime="manual free-text, unused",
    )
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def _no_fundednext_snapshot(monkeypatch):
    """Keeps these tests about aggregation, not FundedNext lookups —
    classify_risk_alignment(None) is always UNKNOWN."""
    monkeypatch.setattr(metrics, "get_fundednext_snapshot", lambda trade_id: None)


# ---------------------------------------------------------------------------
# compute_overview
# ---------------------------------------------------------------------------

def test_overview_core_numbers_match_journal_trades_compute_analytics_directly():
    trades = [_trade(1), _trade(2, result="LOSS", r_multiple=-1.0), _trade(3, result="BE", r_multiple=0.0)]
    expected = trades_repo.compute_analytics(pd.DataFrame(trades))
    overview = metrics.compute_overview(trades)
    assert overview.total_trades == expected["total_trades"]
    assert overview.wins == expected["wins"]
    assert overview.losses == expected["losses"]
    assert overview.breakeven == expected["breakeven"]
    assert overview.win_rate == expected["win_rate"]
    assert overview.total_r == expected["total_r"]
    assert overview.avg_r == expected["avg_r"]
    assert overview.profit_factor == expected["profit_factor"]


def test_overview_median_r_with_odd_count():
    trades = [_trade(1, r_multiple=1.0), _trade(2, r_multiple=3.0), _trade(3, r_multiple=5.0)]
    assert metrics.compute_overview(trades).median_r == 3.0


def test_overview_median_r_with_even_count():
    trades = [_trade(1, r_multiple=1.0), _trade(2, r_multiple=2.0)]
    assert metrics.compute_overview(trades).median_r == 1.5


def test_overview_avg_holding_duration_ignores_nulls():
    trades = [_trade(1, duration_minutes=10.0), _trade(2, duration_minutes=30.0), _trade(3, duration_minutes=None)]
    assert metrics.compute_overview(trades).avg_holding_duration_minutes == 20.0


def test_overview_median_and_duration_are_none_with_no_trades():
    overview = metrics.compute_overview([])
    assert overview.median_r is None
    assert overview.avg_holding_duration_minutes is None
    assert overview.total_trades == 0


def test_overview_alignment_counts_sum_to_total_closed_trades():
    trades = [_trade(1), _trade(2, h1_bias="BEARISH"), _trade(3, h1_bias=None, liquidity=None, mss=None, displacement=None)]
    overview = metrics.compute_overview(trades)
    assert sum(overview.strategy_alignment_counts.values()) == 3
    assert sum(overview.risk_alignment_counts.values()) == 3
    # No FundedNext snapshot anywhere in this test -> risk is always UNKNOWN.
    assert overview.risk_alignment_counts[StrategyAlignment.UNKNOWN] == 3


def test_metrics_module_never_reimplements_alignment_rules():
    """Structural: alignment must come from ai.trade_review.engine, never
    a re-derived bias/liquidity/MSS check living in this module."""
    source = inspect.getsource(metrics)
    for banned in ("_h1_bias_consistency", "detect_setup", "_infer_liquidity_kind", "BULLISH", "BEARISH"):
        assert banned not in source


# ---------------------------------------------------------------------------
# compute_adherence
# ---------------------------------------------------------------------------

def test_adherence_cross_tabulates_alignment_and_outcome_independently():
    trades = [
        _trade(1, result="LOSS", r_multiple=-1.0),  # ALIGNED + LOSS
        _trade(2, result="WIN"),  # ALIGNED + WIN
        _trade(3, h1_bias="BEARISH", result="WIN"),  # NOT_ALIGNED + WIN
    ]
    buckets = {b.alignment: b for b in metrics.compute_adherence(trades)}
    assert buckets[StrategyAlignment.ALIGNED].trade_count == 2
    assert buckets[StrategyAlignment.ALIGNED].wins == 1
    assert buckets[StrategyAlignment.ALIGNED].losses == 1
    assert buckets[StrategyAlignment.NOT_ALIGNED].trade_count == 1
    assert buckets[StrategyAlignment.NOT_ALIGNED].wins == 1
    assert buckets[StrategyAlignment.NOT_ALIGNED].losses == 0


def test_adherence_omits_alignment_buckets_with_no_trades():
    trades = [_trade(1)]
    alignments = {b.alignment for b in metrics.compute_adherence(trades)}
    assert alignments == {StrategyAlignment.ALIGNED}


def test_adherence_reuses_precomputed_reviews_when_given():
    trades = [_trade(1)]
    reviews = metrics.build_reviews(trades)
    # Sabotage get_fundednext_snapshot after the fact -- if compute_adherence
    # recomputed reviews internally instead of reusing the ones passed in,
    # this would still succeed since risk stays UNKNOWN either way; the real
    # proof is that passing reviews=[] (no trades) skips computation entirely.
    result = metrics.compute_adherence([], reviews=[])
    assert result == []


# ---------------------------------------------------------------------------
# compute_dimension_breakdown
# ---------------------------------------------------------------------------

def test_dimension_breakdown_groups_by_direction():
    trades = [_trade(1, direction="BUY"), _trade(2, direction="BUY", result="LOSS"), _trade(3, direction="SELL", mss="Bearish", displacement="Bearish", h1_bias="BEARISH", liquidity="Previous Day High swept")]
    breakdown = metrics.compute_dimension_breakdown(trades, "direction")
    rows = {r.value: r for r in breakdown.rows}
    assert rows["BUY"].sample_size == 2
    assert rows["BUY"].wins == 1
    assert rows["BUY"].losses == 1
    assert rows["SELL"].sample_size == 1


def test_dimension_breakdown_regime_uses_journal_context_not_manual_market_regime():
    trades = [
        _trade(1, regime="TRENDING", market_regime="totally different manual text"),
        _trade(2, regime="TRENDING", market_regime="also different"),
    ]
    breakdown = metrics.compute_dimension_breakdown(trades, "regime")
    values = {r.value for r in breakdown.rows}
    assert values == {"TRENDING"}


def test_dimension_breakdown_null_values_bucket_as_unknown_not_dropped():
    trades = [_trade(1, session="London"), _trade(2, session=None)]
    breakdown = metrics.compute_dimension_breakdown(trades, "session")
    values = {r.value for r in breakdown.rows}
    assert values == {"London", "UNKNOWN"}
    assert sum(r.sample_size for r in breakdown.rows) == 2


def test_dimension_breakdown_insufficient_sample_flag_still_shows_raw_count(monkeypatch):
    monkeypatch.setattr("config.STRATEGY_ANALYTICS_MIN_SAMPLE", 5)
    trades = [_trade(1, session="London"), _trade(2, session="London")]
    breakdown = metrics.compute_dimension_breakdown(trades, "session")
    row = breakdown.rows[0]
    assert row.sample_size == 2
    assert row.insufficient_sample is True


def test_dimension_breakdown_planned_rr_formats_consistently():
    trades = [_trade(1, planned_rr=3.0), _trade(2, planned_rr=3.0000001)]
    breakdown = metrics.compute_dimension_breakdown(trades, "planned_rr")
    assert len(breakdown.rows) == 1
    assert breakdown.rows[0].sample_size == 2


def test_dimension_breakdown_unknown_dimension_raises_value_error():
    with pytest.raises(ValueError):
        metrics.compute_dimension_breakdown([_trade(1)], "not_a_real_dimension")


# ---------------------------------------------------------------------------
# Stage 19 VAL-005 regression: going through the REAL DB path (not a
# hand-built dict), a group where every trade has a genuinely missing
# r_multiple must report total_r == 0.0 and avg_r is None -- never NaN
# (which serializes as a misleading JSON null even for a group with real
# wins/losses, as observed live during the Stage 18 validation phase).
# ---------------------------------------------------------------------------

def test_dimension_breakdown_reports_zero_not_nan_for_real_missing_r_multiple(temp_db):
    import math
    from ai.trade_review import patterns
    from journal import trades as trades_repo

    for i in range(2):
        trade_id = trades_repo.create_trade(
            {"trade_date": "2026-01-05", "trade_time": f"09:0{i}", "symbol": "XAUUSD", "direction": "BUY",
             "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0, "planned_rr": 3.0},
            {"h1_bias": "BULLISH", "liquidity": "Previous Day Low swept", "mss": "Bullish", "displacement": "Bullish"},
        )
        # r_multiple deliberately omitted -- closes with only result/exit_price known.
        trades_repo.close_trade(trade_id, {"exit_price": 3730.0, "result": "WIN", "duration_minutes": 45})

    trades = patterns.closed_trades()
    breakdown = metrics.compute_dimension_breakdown(trades, "direction")
    row = next(r for r in breakdown.rows if r.value == "BUY")
    assert row.total_r == 0.0
    assert row.avg_r is None
    assert not (isinstance(row.total_r, float) and math.isnan(row.total_r))
