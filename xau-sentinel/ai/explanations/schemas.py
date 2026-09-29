"""Pydantic contract for the explanations API — a typed mirror of
ai/explanations/models.py::AlertExplanation, never a place new data gets
invented."""
from typing import List, Optional

from pydantic import BaseModel


class AlertExplanationOut(BaseModel):
    subject_type: str
    subject_id: int
    explanation_type: str
    summary: str
    deterministic_facts: List[str]
    supporting_context: List[str]
    risk_context: List[str]
    historical_context: str
    knowledge_context: List[str]
    memory_context: List[str]
    uncertainties: List[str]
    interpretation: str
    sources: List[str]
    generated_at: str
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None
