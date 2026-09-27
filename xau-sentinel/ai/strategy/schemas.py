"""Structured output contracts for the A+ strategy evaluator (Stage 4).

Used directly as return types from ai/strategy/evaluator.py's pure functions
(not just as an API response shape) — there is no separate internal
dataclass layer to keep in sync, so these are exactly what gets tested and
exactly what the API returns.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class Rating(str, Enum):
    A_PLUS = "A+"
    DEVELOPING = "DEVELOPING"
    INVALID = "INVALID"


class CriterionStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Criterion(BaseModel):
    """One mandatory deterministic requirement from the locked strategy
    spec. `evidence` is the specific fact(s) that produced `status` — never
    the LLM's wording, always built from the deterministic engines'
    output."""
    name: str
    status: CriterionStatus
    evidence: str
    required: bool = True


class FundedNextGateOut(BaseModel):
    """The FundedNext figures the A+ gate (item 11) was evaluated against —
    a snapshot for THIS evaluation, distinct from (and not a replacement
    for) risk/fundednext_journal.py's per-trade immutable snapshots."""
    data_available: bool
    safety_level: Optional[str] = None
    daily_loss_used_pct: Optional[float] = None
    max_daily_loss_used_pct_allowed: float
    reason: Optional[str] = None


class StrategyEvaluationOut(BaseModel):
    rating: Rating
    direction: Optional[str] = None  # "BUY" | "SELL" | None (no candidate)

    criteria: List[Criterion] = []
    # Non-gating supporting facts (H4/M15 bias, equal highs/lows, etc.) —
    # explicitly never used to satisfy a mandatory criterion.
    context_evidence: List[str] = []
    missing_conditions: List[str] = []
    invalidation: Optional[str] = None

    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    rr: Optional[float] = None

    fundednext: FundedNextGateOut

    evaluated_at: str
    candidate_sweep_time: Optional[str] = None

    # LLM enrichment — explanation only, never influences `rating` above,
    # which is fully decided before this is attached. Absent/None means the
    # provider was unavailable or failed; the deterministic result is
    # unaffected either way (see ai/strategy/evaluator.py::attach_llm_explanation).
    llm_explanation: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None
