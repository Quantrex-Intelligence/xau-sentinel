"""Pydantic contracts for the digest API — typed mirrors of
ai/digest/models.py, reusing ai.strategy_analytics.schemas.OverviewOut and
ai.trade_review.schemas.BehavioralPatternOut as nested fields rather than
redefining them."""
from typing import Dict, List, Optional

from pydantic import BaseModel

from ai.strategy_analytics.schemas import OverviewOut
from ai.trade_review.schemas import BehavioralPatternOut


class PeriodComparisonOut(BaseModel):
    current_trade_count: int
    current_total_r: float
    current_avg_r: float
    current_win_rate: float
    current_strategy_alignment_counts: Dict[str, int]
    previous_trade_count: int
    previous_total_r: float
    previous_avg_r: float
    previous_win_rate: float
    previous_strategy_alignment_counts: Dict[str, int]


class DigestSummaryOut(BaseModel):
    digest_type: str
    period_start: str
    period_end: str  # half-open: exclusive, the first day of the NEXT period -- see ai/digest/models.py
    generated_at: str
    overview: OverviewOut
    behavioral_patterns: List[BehavioralPatternOut]
    previous_period: Optional[PeriodComparisonOut] = None


class DigestStatusOut(BaseModel):
    enabled: bool
    weekly_enabled: bool
    monthly_enabled: bool
    weekly_day: str
    weekly_time: str
    monthly_day: int
    monthly_time: str
    provider: str
    configured: bool
    last_sent_weekly: Optional[str] = None
    last_sent_monthly: Optional[str] = None


class DigestSendResultOut(BaseModel):
    sent: bool
    already_sent: bool
    error: Optional[str] = None
    summary: DigestSummaryOut
