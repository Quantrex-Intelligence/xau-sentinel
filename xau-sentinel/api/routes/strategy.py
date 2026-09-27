"""A+ strategy evaluation route — a thin wrapper over
ai.strategy.evaluator.evaluate_current_setup(). Logs a non-duplicating A+
alert as a side effect when (and only when) the deterministic evaluator
returns A+ — this route owns that side effect, the same way
api/routes/journal.py owns the FundedNext-snapshot write after calling the
pure journal.trades.create_trade().
"""
from fastapi import APIRouter, HTTPException

from journal import trades as trades_repo
from mt5 import market_data

from ai.strategy.evaluator import evaluate_current_setup
from ai.strategy.schemas import Rating, StrategyEvaluationOut

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/aplus", response_model=StrategyEvaluationOut)
def get_aplus_evaluation():
    try:
        result = evaluate_current_setup()
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if result.rating == Rating.A_PLUS and result.candidate_sweep_time:
        dedup_key = f"{result.direction}:{result.candidate_sweep_time}"
        if not trades_repo.has_recent_alert("a_plus", result.direction, dedup_key):
            trades_repo.log_alert(
                level="a_plus", direction=result.direction,
                message=f"{result.direction} A+ setup confirmed — entry {result.entry}, "
                        f"SL {result.stop_loss}, target {result.target}, R:R 1:{result.rr}.",
                details={"dedup_key": dedup_key, "criteria": [c.model_dump() for c in result.criteria]},
            )

    return result
