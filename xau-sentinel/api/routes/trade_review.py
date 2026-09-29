"""Trade review routes (Stage 16) — thin pass-throughs into
ai.trade_review.service; no rule/engine/LLM logic lives here.

GET /trade-review/{id} NEVER calls the LLM (only
ai.trade_review.service.get_review(), which only calls
ai.trade_review.engine.build_trade_review() — deterministic, no provider
call). Generation is the one, separate, explicit POST action.
"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ai.trade_review import patterns, service
from ai.trade_review.schemas import TradeReviewOut, TradeReviewSummaryOut

router = APIRouter(prefix="/api/trade-review", tags=["trade-review"])


def _out(review) -> TradeReviewOut:
    data = asdict(review)
    data["outcome"] = review.outcome.value
    data["strategy_alignment"] = review.strategy_alignment.value
    data["setup_alignment"] = review.setup_alignment.value
    data["execution_alignment"] = review.execution_alignment.value
    data["risk_alignment"] = review.risk_alignment.value
    data["deviations"] = [{"type": d.type.value, "evidence": d.evidence} for d in review.deviations]
    return TradeReviewOut(**data)


@router.get("/summary", response_model=TradeReviewSummaryOut)
def get_summary():
    summary = patterns.build_summary()
    data = asdict(summary)
    data["patterns"] = [
        {**asdict(p), "deviation_type": p.deviation_type.value} for p in summary.patterns
    ]
    return TradeReviewSummaryOut(**data)


@router.get("/patterns")
def get_patterns():
    trades = patterns.closed_trades()
    found = patterns.aggregate_patterns(trades)
    return [{**asdict(p), "deviation_type": p.deviation_type.value} for p in found]


@router.get("/{trade_id}", response_model=TradeReviewOut)
def get_trade_review(trade_id: int):
    try:
        review = service.get_review(trade_id)
    except service.TradeReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _out(review)


@router.post("/{trade_id}/generate", response_model=TradeReviewOut)
def generate_trade_review(trade_id: int):
    try:
        review = service.generate_review(trade_id)
    except service.TradeReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _out(review)
