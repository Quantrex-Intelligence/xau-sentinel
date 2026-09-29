"""Tests for ai/trade_review/patterns.py — one trade never creates a
reported pattern, repeated observations are counted correctly with
correct denominators, sample_count is exposed, and trades_with_loss is a
labeled association, never phrased as causation."""
import pytest

from ai.trade_review import patterns
from ai.trade_review.models import DeviationType


def _trade(trade_id, **overrides):
    defaults = dict(
        id=trade_id, status="CLOSED", result="WIN", direction="BUY",
        h1_bias="BULLISH", liquidity="Previous Day Low swept", mss="Bullish", displacement="Bullish",
        planned_rr=3.0,
    )
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def _no_fundednext_snapshot(monkeypatch):
    """Keep these tests about deviation aggregation, not FundedNext
    per-trade lookups — no snapshot means RISK_LIMIT_DEVIATION never
    fires here, isolating the fields under test."""
    monkeypatch.setattr(patterns, "get_fundednext_snapshot", lambda trade_id: None)


def test_aggregate_patterns_returns_nothing_for_an_empty_list():
    assert patterns.aggregate_patterns([]) == []


def test_one_trade_never_creates_a_reported_pattern(monkeypatch):
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 3)
    trades = [_trade(1, h1_bias="BEARISH")]  # a single DIRECTION_DEVIATION
    result = patterns.aggregate_patterns(trades)
    assert result == []


def test_repeated_deviation_is_counted_with_correct_denominator(monkeypatch):
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 3)
    trades = [
        _trade(1, h1_bias="BEARISH"), _trade(2, h1_bias="BEARISH"), _trade(3, h1_bias="BEARISH"),
        _trade(4),  # aligned, no deviation
    ]
    result = patterns.aggregate_patterns(trades)
    direction_pattern = next(p for p in result if p.deviation_type == DeviationType.DIRECTION_DEVIATION)
    assert direction_pattern.sample_count == 3
    assert direction_pattern.total_relevant_trades == 4
    assert direction_pattern.occurrence_rate == 0.75


def test_pattern_below_threshold_is_excluded(monkeypatch):
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 5)
    trades = [_trade(1, h1_bias="BEARISH"), _trade(2, h1_bias="BEARISH")]
    assert patterns.aggregate_patterns(trades) == []


def test_trades_with_loss_counted_and_labeled_as_association_not_causation(monkeypatch):
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 2)
    trades = [
        _trade(1, h1_bias="BEARISH", result="LOSS"),
        _trade(2, h1_bias="BEARISH", result="LOSS"),
        _trade(3, h1_bias="BEARISH", result="WIN"),
    ]
    result = patterns.aggregate_patterns(trades)
    direction_pattern = next(p for p in result if p.deviation_type == DeviationType.DIRECTION_DEVIATION)
    assert direction_pattern.trades_with_loss == 2
    assert "causation" in direction_pattern.note.lower()
    assert "not evidence of causation" in direction_pattern.note.lower()


def test_pattern_note_never_claims_a_deviation_causes_losses(monkeypatch):
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 2)
    trades = [_trade(1, h1_bias="BEARISH", result="LOSS"), _trade(2, h1_bias="BEARISH", result="LOSS")]
    result = patterns.aggregate_patterns(trades)
    for pattern in result:
        lowered = pattern.note.lower()
        assert "cause" not in lowered or "not evidence of causation" in lowered
        assert "will" not in lowered


def test_build_summary_counts_strategy_alignment_across_closed_trades(monkeypatch):
    monkeypatch.setattr(patterns.trades_repo, "list_trades", lambda: _df([
        _trade(1), _trade(2, h1_bias="BEARISH"), _trade(3, h1_bias=None, liquidity=None, mss=None, displacement=None),
    ]))
    summary = patterns.build_summary()
    assert summary.trades_reviewed == 3
    assert summary.strategy_aligned == 1
    assert summary.not_aligned == 1
    assert summary.unknown == 1
    assert summary.partially_aligned == 0


def test_build_summary_excludes_open_trades(monkeypatch):
    monkeypatch.setattr(patterns.trades_repo, "list_trades", lambda: _df([
        _trade(1), _trade(2, status="OPEN", result=None),
    ]))
    summary = patterns.build_summary()
    assert summary.trades_reviewed == 1


def test_build_summary_reports_insufficient_sample_note_when_below_threshold(monkeypatch):
    monkeypatch.setattr("config.TRADE_REVIEW_MIN_PATTERN_SAMPLE", 5)
    monkeypatch.setattr(patterns.trades_repo, "list_trades", lambda: _df([_trade(1)]))
    summary = patterns.build_summary()
    assert summary.insufficient_sample_note is not None
    assert "insufficient" in summary.insufficient_sample_note.lower()


def _df(records):
    import pandas as pd
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Stage 19 VAL-005 regression: closed_trades() must go through the REAL
# DataFrame -> dict pipeline (temp_db + journal.trades), not a hand-built
# fixture, since that's the only way the pandas float64 NaN-vs-None gotcha
# actually surfaces (df.where(df.notnull(), None) silently no-ops on a
# float64 column -- every hand-built dict fixture in this file bypasses
# that entirely).
# ---------------------------------------------------------------------------

def test_closed_trades_reports_a_genuinely_missing_planned_rr_as_none_not_nan(temp_db):
    import math
    from journal import trades as trades_repo

    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-05", "trade_time": "09:00", "symbol": "XAUUSD", "direction": "BUY",
         "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0},  # planned_rr deliberately omitted
        {"h1_bias": "BULLISH", "liquidity": "Previous Day Low swept", "mss": "Bullish", "displacement": "Bullish"},
    )
    trades_repo.close_trade(trade_id, {"exit_price": 3730.0, "result": "WIN", "pnl": 300.0,
                                        "r_multiple": 3.0, "duration_minutes": 45})

    trade = next(t for t in patterns.closed_trades() if t["id"] == trade_id)
    planned_rr = trade.get("planned_rr")
    assert planned_rr is None
    assert not (isinstance(planned_rr, float) and math.isnan(planned_rr))
