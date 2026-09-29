"""Deterministic trade review assembly (Stage 16) — the ONE function the
Journal UI calls on trade-detail load. No LLM, no HTTP, no live market/
account calls; pure over the trade's own historical, stored fields. Every
field here is finalized before ai/trade_review/service.py ever calls an
LLM — the interpretation step can only ever add `interpretation`, never
change anything built here (see ai/trade_review/models.py::TradeReview).
"""
from typing import Any, Dict, Optional

from ai.trade_review import rules
from ai.trade_review.models import TradeReview


def build_trade_review(trade: Dict[str, Any], fundednext_snapshot: Optional[Dict[str, Any]]) -> TradeReview:
    consistencies = rules.dimension_consistencies(trade)
    setup_alignment = rules.classify_setup_alignment(trade)
    execution_alignment = rules.classify_execution_alignment(trade)
    risk_alignment = rules.classify_risk_alignment(fundednext_snapshot)
    strategy_alignment = rules.classify_strategy_alignment(setup_alignment, execution_alignment)

    return TradeReview(
        trade_id=trade["id"],
        outcome=rules.classify_outcome(trade),
        strategy_alignment=strategy_alignment,
        setup_alignment=setup_alignment,
        execution_alignment=execution_alignment,
        risk_alignment=risk_alignment,
        deviations=rules.detect_deviations(trade, fundednext_snapshot),
        rule_observations=rules.build_rule_observations(trade, consistencies),
        r_multiple=trade.get("r_multiple"),
        holding_duration_minutes=trade.get("duration_minutes"),
    )
