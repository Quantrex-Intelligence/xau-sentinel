"""Data shapes for the Entry Model V2 LLM Setup Judge. Pure data only, same convention as
ai/explanations/models.py::AlertExplanation -- every field here is either plain Python (built before
any LLM call) or the LLM's own structured reply, never a mix within one field.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

STATUS_OK = "OK"
STATUS_FAILED = "FAILED"


@dataclass
class EntryJudgeVerdict:
    """The LLM's structured reply, once parsed and schema-validated. Never constructed from a
    failed/malformed response -- see evaluator.py."""
    verdict: str  # SUPPORTED | CAUTION | REJECTED | INSUFFICIENT_EVIDENCE
    quality: str  # HIGH | MODERATE | LOW | UNASSESSABLE
    supporting_evidence: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    missing_confirmations: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    reasoning_summary: str = ""
    invalidation_conditions: List[str] = field(default_factory=list)
    evidence_references: List[str] = field(default_factory=list)
    model_id: str = ""
    prompt_version: str = ""


@dataclass
class StoredJudgment:
    """One row of journal/schema.py::entry_model_judgments, in Python form. `verdict`/`quality`/
    `verdict_payload` are None exactly when `status == STATUS_FAILED` -- a failure is recorded
    honestly, never papered over with a fabricated verdict (see evaluator.py's own docstring)."""
    candidate_key: str
    direction: str
    state: str
    symbol: str
    snapshot_fingerprint: str
    snapshot: dict
    candidate_created_at: datetime
    evaluated_at: datetime
    prompt_version: str
    status: str  # STATUS_OK | STATUS_FAILED
    is_reassessment: bool
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    error_category: Optional[str] = None  # "config" | "request" | "timeout" | "malformed_response" | "schema_invalid" | "unexpected"
    verdict: Optional[EntryJudgeVerdict] = None
    id: Optional[int] = None
