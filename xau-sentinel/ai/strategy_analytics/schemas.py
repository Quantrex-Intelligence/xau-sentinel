"""Pydantic contracts for the strategy-analytics API — typed mirrors of
ai/strategy_analytics/models.py, never a place new data gets invented."""
from typing import Dict, List, Optional

from pydantic import BaseModel


class OverviewOut(BaseModel):
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    total_r: float
    avg_r: float
    profit_factor: Optional[float] = None
    median_r: Optional[float] = None
    avg_holding_duration_minutes: Optional[float] = None
    strategy_alignment_counts: Dict[str, int]
    risk_alignment_counts: Dict[str, int]


class AdherenceBucketOut(BaseModel):
    alignment: str
    trade_count: int
    wins: int
    losses: int
    breakeven: int
    open: int
    unknown: int


class StrategyAnalyticsOut(BaseModel):
    overview: OverviewOut
    adherence: List[AdherenceBucketOut]


class DimensionRowOut(BaseModel):
    value: str
    sample_size: int
    wins: int
    losses: int
    breakeven: int
    win_rate: Optional[float] = None
    avg_r: Optional[float] = None
    total_r: float
    insufficient_sample: bool


class DimensionBreakdownOut(BaseModel):
    dimension: str
    rows: List[DimensionRowOut]
