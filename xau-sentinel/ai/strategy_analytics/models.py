"""Data shapes for Strategy Analytics (Stage 17). Pure data only — every
count/rate here is a plain aggregation, never a prediction or a score."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ai.trade_review.models import Outcome, StrategyAlignment


@dataclass
class OverviewMetrics:
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    total_r: float
    avg_r: float
    profit_factor: Optional[float]
    median_r: Optional[float]
    avg_holding_duration_minutes: Optional[float]
    strategy_alignment_counts: Dict[StrategyAlignment, int]
    risk_alignment_counts: Dict[StrategyAlignment, int]


@dataclass
class AdherenceBucket:
    alignment: StrategyAlignment
    trade_count: int
    wins: int
    losses: int
    breakeven: int
    open: int
    unknown: int


@dataclass
class DimensionRow:
    value: str
    sample_size: int
    wins: int
    losses: int
    breakeven: int
    win_rate: Optional[float]
    avg_r: Optional[float]
    total_r: float
    insufficient_sample: bool


@dataclass
class DimensionBreakdown:
    dimension: str
    rows: List[DimensionRow] = field(default_factory=list)
