"""Pydantic contracts for the trade-review API — typed mirrors of
ai/trade_review/models.py, never a place new data gets invented."""
from typing import List, Optional

from pydantic import BaseModel


class DeviationOut(BaseModel):
    type: str
    evidence: str


class TradeReviewOut(BaseModel):
    trade_id: int
    outcome: str
    strategy_alignment: str
    setup_alignment: str
    execution_alignment: str
    risk_alignment: str
    deviations: List[DeviationOut]
    rule_observations: List[str]
    r_multiple: Optional[float] = None
    holding_duration_minutes: Optional[float] = None
    similar_trade_context: str
    behavioral_context: List[str]
    knowledge_context: List[str]
    memory_context: List[str]
    uncertainties: List[str]
    interpretation: Optional[str] = None
    sources: List[str]
    reviewed_at: str
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None


class BehavioralPatternOut(BaseModel):
    deviation_type: str
    sample_count: int
    total_relevant_trades: int
    occurrence_rate: Optional[float] = None
    trades_with_loss: int
    note: str


class TradeReviewSummaryOut(BaseModel):
    trades_reviewed: int
    strategy_aligned: int
    partially_aligned: int
    not_aligned: int
    unknown: int
    patterns: List[BehavioralPatternOut]
    insufficient_sample_note: Optional[str] = None
