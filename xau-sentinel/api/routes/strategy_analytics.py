"""Strategy analytics routes (Stage 17) — thin pass-throughs into
ai.strategy_analytics.metrics; no aggregation logic lives here. Nothing
in this module writes to any table — every response is computed fresh
from trades/journal_context/fundednext_context on each request.
"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ai.strategy_analytics import metrics
from ai.trade_review import patterns
from ai.strategy_analytics.schemas import (
    AdherenceBucketOut, DimensionBreakdownOut, OverviewOut, StrategyAnalyticsOut,
)

router = APIRouter(prefix="/api/strategy-analytics", tags=["strategy-analytics"])


@router.get("", response_model=StrategyAnalyticsOut)
def get_strategy_analytics():
    trades = patterns.closed_trades()
    reviews = metrics.build_reviews(trades)
    overview = metrics.compute_overview(trades, reviews)
    adherence = metrics.compute_adherence(trades, reviews)

    overview_data = asdict(overview)
    overview_data["strategy_alignment_counts"] = {k.value: v for k, v in overview.strategy_alignment_counts.items()}
    overview_data["risk_alignment_counts"] = {k.value: v for k, v in overview.risk_alignment_counts.items()}

    return StrategyAnalyticsOut(
        overview=OverviewOut(**overview_data),
        adherence=[AdherenceBucketOut(**{**asdict(a), "alignment": a.alignment.value}) for a in adherence],
    )


@router.get("/dimensions/{dimension}", response_model=DimensionBreakdownOut)
def get_dimension_breakdown(dimension: str):
    trades = patterns.closed_trades()
    try:
        breakdown = metrics.compute_dimension_breakdown(trades, dimension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DimensionBreakdownOut(**asdict(breakdown))
