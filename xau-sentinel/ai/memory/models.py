"""Data shapes for the trading memory layer. Pure data — no storage or
retrieval logic lives here."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MemoryCategory(str, Enum):
    USER_PREFERENCE = "USER_PREFERENCE"
    STRATEGY_MEMORY = "STRATEGY_MEMORY"
    TRADE_LESSON = "TRADE_LESSON"
    PATTERN_OBSERVATION = "PATTERN_OBSERVATION"


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@dataclass
class MemoryRecord:
    id: int
    category: MemoryCategory
    content: str
    source: str  # always "user_confirmed" — see ai/memory/store.py::create_memory
    status: MemoryStatus
    created_at: str
    updated_at: str
    strategy_version: Optional[str] = None


@dataclass
class RetrievedMemory:
    """One memory record returned by retrieval, carrying its similarity
    score — the UI and the prompt both need it without a second lookup."""
    id: int
    category: MemoryCategory
    content: str
    similarity: float
    created_at: str
    updated_at: str
    strategy_version: Optional[str] = None
