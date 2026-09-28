"""Pydantic contracts for the AI assistant API — mirrors api/schemas.py's
convention: these are typed shapes for what ai/assistant.py already
produces, never a place where new data gets invented or reshaped."""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from ai.knowledge.schemas import KnowledgeSourceOut
from ai.tools.schemas import ToolUsageOut


class AnswerCategory(str, Enum):
    """How a piece of information relates to ground truth (Stage 3 spec
    section 3). FACT/CALCULATION trace to a deterministic engine;
    INTERPRETATION is the LLM's own reading of those facts; UNKNOWN means
    the data needed to answer isn't available and must not be guessed."""
    FACT = "FACT"
    CALCULATION = "CALCULATION"
    INTERPRETATION = "INTERPRETATION"
    UNKNOWN = "UNKNOWN"


class ContextSourceOut(BaseModel):
    """One traceable input the answer was built from. The UI's "Context
    used" transparency panel renders this list directly — it is never
    inferred after the fact from the LLM's own text."""
    label: str  # "Market Structure" | "Setup" | "FundedNext Risk" | "Journal"
    category: AnswerCategory
    available: bool
    detail: Optional[str] = None


class ChatRequestIn(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    # Subset of "market", "risk", "journal". None -> ai.context.DEFAULT_SCOPES.
    context_scope: Optional[List[str]] = None
    # When set, replaces context_scope entirely: explain THIS trade using
    # only what was captured at entry (see ai/context.py::build_trade_section).
    trade_id: Optional[int] = None


class ChatResponseOut(BaseModel):
    answer: str
    conversation_id: str
    context_used: List[str]
    sources: List[ContextSourceOut]
    category: AnswerCategory  # the answer's overall category
    provider: Optional[str] = None
    model: Optional[str] = None
    created_at: str
    # Stage 5: reference knowledge retrieved for this turn, alongside (never
    # replacing) the deterministic sources above. Empty when nothing cleared
    # the relevance threshold — never a fabricated or forced match.
    knowledge_used: List[KnowledgeSourceOut] = []
    # Stage 6: read-only tools the model actually called this turn, in call
    # order — the UI's "Tools used" transparency panel renders this list
    # directly. Empty when the answer needed no tool call.
    tools_used: List[ToolUsageOut] = []


class AiConfigOut(BaseModel):
    """Lets the frontend show a configuration error up front, before the
    user sends a message. Never carries the API key itself."""
    configured: bool
    provider: str
    model: Optional[str] = None
    reason: Optional[str] = None
