"""Deterministic aggregation over completed journal trades (Stage 17) —
pure functions, no LLM. Core win/loss/rate numbers are delegated to
journal.trades.compute_analytics() (frozen file, read-only reuse) rather
than reimplemented; alignment/outcome per trade is delegated to
ai.trade_review.engine.build_trade_review() (Stage 16, also read-only
reuse) rather than re-derived. Nothing here writes to any table.
"""
import statistics
from typing import Any, Dict, List, Optional

import pandas as pd

import config
from journal import trades as trades_repo
from risk.fundednext_journal import get_snapshot as get_fundednext_snapshot
from ai.trade_review import engine
from ai.trade_review.models import Outcome, StrategyAlignment, TradeReview
from ai.strategy_analytics.models import AdherenceBucket, DimensionBreakdown, DimensionRow, OverviewMetrics

# The fixed set of breakdown dimensions this stage supports, and the trade
# record key each one reads. "regime" reads journal_context's auto-captured
# regime (what the Journal UI itself already labels "Regime"), deliberately
# not trades.market_regime (a separate, manually-typed free-text field) —
# see the Stage 17 plan's "Dimension field mapping" section.
DIMENSION_KEYS = {
    "direction": "direction",
    "h1_bias": "h1_bias",
    "session": "session",
    "regime": "regime",
    "liquidity": "liquidity",
    "planned_rr": "planned_rr",
}

_ALIGNMENTS = [
    StrategyAlignment.ALIGNED, StrategyAlignment.PARTIALLY_ALIGNED,
    StrategyAlignment.NOT_ALIGNED, StrategyAlignment.UNKNOWN,
]
_OUTCOMES = [Outcome.WIN, Outcome.LOSS, Outcome.BREAKEVEN, Outcome.OPEN, Outcome.UNKNOWN]


def build_reviews(trades: List[Dict[str, Any]]) -> List[TradeReview]:
    """One ai.trade_review.engine.build_trade_review() call per trade — the
    single source of truth for outcome/strategy_alignment/risk_alignment.
    Same per-request N+1 FundedNext lookup ai/trade_review/patterns.py's
    build_summary() already accepts as fine at this project's scale."""
    reviews = []
    for trade in trades:
        snapshot = get_fundednext_snapshot(trade["id"])
        reviews.append(engine.build_trade_review(trade, snapshot))
    return reviews


def compute_overview(trades: List[Dict[str, Any]], reviews: Optional[List[TradeReview]] = None) -> OverviewMetrics:
    reviews = reviews if reviews is not None else build_reviews(trades)

    df = pd.DataFrame(trades)
    core = trades_repo.compute_analytics(df)

    r_values = [t.get("r_multiple") for t in trades if t.get("r_multiple") is not None]
    median_r = round(statistics.median(r_values), 2) if r_values else None

    durations = [t.get("duration_minutes") for t in trades if t.get("duration_minutes") is not None]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None

    strategy_counts = {a: 0 for a in _ALIGNMENTS}
    risk_counts = {a: 0 for a in _ALIGNMENTS}
    for review in reviews:
        strategy_counts[review.strategy_alignment] += 1
        risk_counts[review.risk_alignment] += 1

    return OverviewMetrics(
        total_trades=core["total_trades"], wins=core["wins"], losses=core["losses"],
        breakeven=core["breakeven"], win_rate=core["win_rate"], total_r=core["total_r"],
        avg_r=core["avg_r"], profit_factor=core["profit_factor"],
        median_r=median_r, avg_holding_duration_minutes=avg_duration,
        strategy_alignment_counts=strategy_counts, risk_alignment_counts=risk_counts,
    )


def compute_adherence(trades: List[Dict[str, Any]], reviews: Optional[List[TradeReview]] = None) -> List[AdherenceBucket]:
    """A plain cross-tabulation of two already-independent fields (see
    ai/trade_review's own structural proof that classify_outcome() never
    reads alignment) — never phrased as one causing the other."""
    reviews = reviews if reviews is not None else build_reviews(trades)

    buckets = {a: {o: 0 for o in _OUTCOMES} for a in _ALIGNMENTS}
    for review in reviews:
        buckets[review.strategy_alignment][review.outcome] += 1

    result = []
    for alignment in _ALIGNMENTS:
        counts = buckets[alignment]
        trade_count = sum(counts.values())
        if trade_count == 0:
            continue
        result.append(AdherenceBucket(
            alignment=alignment, trade_count=trade_count,
            wins=counts[Outcome.WIN], losses=counts[Outcome.LOSS], breakeven=counts[Outcome.BREAKEVEN],
            open=counts[Outcome.OPEN], unknown=counts[Outcome.UNKNOWN],
        ))
    return result


def compute_dimension_breakdown(trades: List[Dict[str, Any]], dimension: str) -> DimensionBreakdown:
    if dimension not in DIMENSION_KEYS:
        raise ValueError(f"Unknown dimension: {dimension!r}. Must be one of {sorted(DIMENSION_KEYS)}.")
    key = DIMENSION_KEYS[dimension]

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for trade in trades:
        value = trade.get(key)
        if value is None:
            label = "UNKNOWN"
        elif dimension == "planned_rr":
            label = f"{float(value):.2f}"
        else:
            label = str(value)
        groups.setdefault(label, []).append(trade)

    rows = []
    for label, group in groups.items():
        sample_size = len(group)
        wins = sum(1 for t in group if t.get("result") == "WIN")
        losses = sum(1 for t in group if t.get("result") == "LOSS")
        breakeven = sum(1 for t in group if t.get("result") == "BE")
        win_rate = round(wins / sample_size * 100, 1) if sample_size else None
        r_values = [t.get("r_multiple") for t in group if t.get("r_multiple") is not None]
        avg_r = round(sum(r_values) / len(r_values), 2) if r_values else None
        total_r = round(sum(r_values), 2) if r_values else 0.0

        rows.append(DimensionRow(
            value=label, sample_size=sample_size, wins=wins, losses=losses, breakeven=breakeven,
            win_rate=win_rate, avg_r=avg_r, total_r=total_r,
            insufficient_sample=sample_size < config.STRATEGY_ANALYTICS_MIN_SAMPLE,
        ))

    rows.sort(key=lambda r: r.sample_size, reverse=True)
    return DimensionBreakdown(dimension=dimension, rows=rows)
