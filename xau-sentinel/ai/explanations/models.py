"""Data shapes for the AI Alert & Trade Explanation Layer (Stage 15).

Pure data only. `AlertExplanation` mirrors the spec's own schema field for
field — every field except `interpretation` is built by plain Python
before any LLM call, exactly like ai/strategy/schemas.py::ContextualAnalysisOut
already establishes for Stage 10. FACT/CONTEXT/INTERPRETATION tiers are
encoded by which field a value lives in (deterministic_facts = FACT;
supporting_context/risk_context/historical_context/knowledge_context/
memory_context = CONTEXT; interpretation = the one INTERPRETATION field),
never by a wrapper object on every item.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class AlertExplanation:
    subject_type: str  # "alert" | "trade"
    subject_id: int
    explanation_type: str  # an AlertType value, or "TRADE"
    summary: str
    deterministic_facts: List[str] = field(default_factory=list)
    supporting_context: List[str] = field(default_factory=list)
    risk_context: List[str] = field(default_factory=list)
    historical_context: str = ""
    knowledge_context: List[str] = field(default_factory=list)
    memory_context: List[str] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)
    interpretation: str = ""
    sources: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_error: Optional[str] = None
