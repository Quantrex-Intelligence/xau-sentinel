"""Data shapes for Trade Review & Behavioral Intelligence (Stage 16).

Pure data only. Explicit enums throughout — never a numeric "confidence"
or "quality" score, matching every prior stage's own convention.
`Outcome` and the alignment fields are structurally independent: nothing
in this module derives one from the other (see ai/trade_review/rules.py —
a WIN with NOT_ALIGNED and a LOSS with ALIGNED are both representable and
both valid).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class StrategyAlignment(str, Enum):
    ALIGNED = "ALIGNED"
    PARTIALLY_ALIGNED = "PARTIALLY_ALIGNED"
    NOT_ALIGNED = "NOT_ALIGNED"
    UNKNOWN = "UNKNOWN"


class Outcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


class DeviationType(str, Enum):
    # Well-evidenced — real detectors, see ai/trade_review/rules.py.
    DIRECTION_DEVIATION = "DIRECTION_DEVIATION"
    MISSED_CONFIRMATION = "MISSED_CONFIRMATION"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    OUTSIDE_STRATEGY = "OUTSIDE_STRATEGY"
    INSUFFICIENT_RR = "INSUFFICIENT_RR"
    RISK_LIMIT_DEVIATION = "RISK_LIMIT_DEVIATION"
    # Defined to complete the taxonomy but never fire against this
    # journal's schema — no planned-vs-actual price/timing pair exists to
    # compare (see the Stage 16 plan's "Critical discovery" section).
    EARLY_ENTRY = "EARLY_ENTRY"
    LATE_ENTRY = "LATE_ENTRY"
    SL_DEVIATION = "SL_DEVIATION"
    TP_DEVIATION = "TP_DEVIATION"
    INVALIDATED_SETUP_TRADED = "INVALIDATED_SETUP_TRADED"


@dataclass
class Deviation:
    type: DeviationType
    evidence: str


@dataclass
class TradeReview:
    trade_id: int
    outcome: Outcome
    strategy_alignment: StrategyAlignment
    setup_alignment: StrategyAlignment
    execution_alignment: StrategyAlignment
    risk_alignment: StrategyAlignment
    deviations: List[Deviation] = field(default_factory=list)
    rule_observations: List[str] = field(default_factory=list)
    r_multiple: Optional[float] = None
    holding_duration_minutes: Optional[float] = None
    similar_trade_context: str = ""
    behavioral_context: List[str] = field(default_factory=list)
    knowledge_context: List[str] = field(default_factory=list)
    memory_context: List[str] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)
    interpretation: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    reviewed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None


@dataclass
class BehavioralPattern:
    deviation_type: DeviationType
    sample_count: int
    total_relevant_trades: int
    occurrence_rate: Optional[float]  # sample_count / total_relevant_trades, None if undefined
    trades_with_loss: int
    note: str  # e.g. "Observed historical association, not evidence of causation."


@dataclass
class TradeReviewSummary:
    trades_reviewed: int
    strategy_aligned: int
    partially_aligned: int
    not_aligned: int
    unknown: int
    patterns: List[BehavioralPattern] = field(default_factory=list)
    insufficient_sample_note: Optional[str] = None
