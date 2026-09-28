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


class MarketIntelligenceSummaryOut(BaseModel):
    """Short, deterministic text summaries per Market Intelligence category
    (Stage 10) — never the full raw snapshot (that duplicates
    ai/market_intelligence/schemas.py unnecessarily) and never LLM prose.
    `relevant=False` means nothing here cleared the bar (no HIGH-importance
    event, no news) — the other fields stay None rather than being padded
    with low-signal detail, per the "relevant evidence, not maximum
    context" requirement."""
    relevant: bool
    macro: Optional[str] = None
    events: Optional[str] = None
    news: Optional[str] = None
    cross_asset: Optional[str] = None


class ContextualAnalysisOut(BaseModel):
    """Stage 10's structured synthesis, attached to StrategyEvaluationOut
    alongside (never replacing) the existing `llm_explanation` fields.
    `rating`/`deterministic_rating` are ALWAYS copied from the already-
    decided StrategyEvaluationOut.rating — there is no code path that asks
    the LLM for a rating at all, so it cannot set one independently (see
    ai/strategy/evidence.py). Every field except `interpretation` is built
    by plain Python from `result`/`ContextualEvidence`, never parsed out of
    the model's own text — the same "LLM never becomes the source of
    truth" rule this project has used since Stage 3."""
    rating: Rating
    deterministic_rating: Rating

    technical_summary: str
    strategy_summary: str
    market_intelligence: MarketIntelligenceSummaryOut
    historical_context: str
    risk_context: str

    # The one and only LLM-authored field — still passed through the same
    # safety filters as llm_explanation before being attached.
    interpretation: str
    # Deterministic — built from missing_conditions plus each evidence
    # source's own relevance flag, never invented.
    uncertainties: List[str] = []

    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None


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

    # Stage 10 — a structured synthesis across every evidence source,
    # alongside (never replacing) llm_explanation above. None when the
    # caller never asked for it (see ai/strategy/evaluator.py::
    # attach_llm_explanation's `evidence` parameter) — every pre-Stage-10
    # caller keeps getting exactly None here, unchanged.
    contextual_analysis: Optional[ContextualAnalysisOut] = None
