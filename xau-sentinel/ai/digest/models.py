"""Data shapes for the Periodic Trading Digest (Stage 18). Pure data only.

DigestSummary embeds ai.strategy_analytics.models.OverviewMetrics and
ai.trade_review.models.BehavioralPattern directly rather than redefining
their fields — the digest is a period-filtered view over those stages'
own existing computations, never a new analytics engine (see the Stage
18 plan)."""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional

from ai.strategy_analytics.models import OverviewMetrics
from ai.trade_review.models import BehavioralPattern, StrategyAlignment


class DigestType(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


@dataclass
class PeriodComparison:
    """Plain, neutral facts about the previous equivalent period — never
    phrased as "better"/"worse"/"improving"/"deteriorating" anywhere this
    is read (see ai/digest/formatter.py)."""
    current_trade_count: int
    current_total_r: float
    current_avg_r: float
    current_win_rate: float
    current_strategy_alignment_counts: Dict[StrategyAlignment, int]
    previous_trade_count: int
    previous_total_r: float
    previous_avg_r: float
    previous_win_rate: float
    previous_strategy_alignment_counts: Dict[StrategyAlignment, int]


@dataclass
class DigestSummary:
    digest_type: DigestType
    period_start: date
    # Half-open interval: period_end is the FIRST DAY OF THE NEXT PERIOD
    # (exclusive), not the last day of this one -- see
    # ai/digest/service.py::compute_period_bounds(). Always the most
    # recently COMPLETED period as of when this was built, never an
    # in-progress one (Stage 20 fix, VAL-004).
    period_end: date
    generated_at: str
    overview: OverviewMetrics
    behavioral_patterns: List[BehavioralPattern] = field(default_factory=list)
    previous_period: Optional[PeriodComparison] = None
