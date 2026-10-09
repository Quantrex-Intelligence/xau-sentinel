"""Structured output contract for the Entry Model V2 LLM Setup Judge. Same convention as
ai/strategy/schemas.py (Pydantic BaseModel, str Enum for closed value sets).

`EntryJudgeVerdictOut` is the strict schema the LLM's reply is validated against -- every field is
required with a closed value set for `verdict`/`quality`, so a reply missing a field, using a value
outside the enum, or not valid JSON at all fails validation (evaluator.py treats that as a recorded
failure, never a guessed/partial verdict).

`quality` is never a win probability and `verdict`/`reasoning_summary` are never a price prediction
or trade instruction -- enforced by the system prompt (prompts.py) and, as a backstop, by running
`reasoning_summary` through ai/prompts.py's existing contains_actionable_directive/
contains_predictive_probability_claim before it is ever stored or shown.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class JudgeVerdictLabel(str, Enum):
    SUPPORTED = "SUPPORTED"
    CAUTION = "CAUTION"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class JudgeQualityLabel(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    UNASSESSABLE = "UNASSESSABLE"


class EntryJudgeVerdictOut(BaseModel):
    """What the LLM must reply with -- a single JSON object matching this shape exactly (see
    prompts.py's system prompt). model_validate_json() on the raw reply text either produces one of
    these or raises; evaluator.py never constructs one from anything else."""
    verdict: JudgeVerdictLabel
    quality: JudgeQualityLabel
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    missing_confirmations: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    invalidation_conditions: List[str] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)


class EntryJudgmentOut(BaseModel):
    """The API's response_model for GET /api/entry-model/judge."""
    enabled: bool
    eligible: bool
    status: Optional[str] = None  # "OK" | "FAILED", None when not eligible
    error_category: Optional[str] = None
    candidate_key: Optional[str] = None
    direction: Optional[str] = None
    state: Optional[str] = None
    symbol: Optional[str] = None
    evaluated_at: Optional[str] = None
    candidate_created_at: Optional[str] = None
    is_reassessment: Optional[bool] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    prompt_version: Optional[str] = None
    verdict: Optional[JudgeVerdictLabel] = None
    quality: Optional[JudgeQualityLabel] = None
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    missing_confirmations: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    reasoning_summary: Optional[str] = None
    invalidation_conditions: List[str] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)
    not_eligible_reason: Optional[str] = None
    disclaimer: str = (
        "SHADOW MODE. This is an independent, experimental LLM review of the deterministic Entry "
        "Model's own evidence. It never affects direction, state, entry, stop, target, or any "
        "trading decision -- the deterministic engine remains the sole source of truth."
    )
