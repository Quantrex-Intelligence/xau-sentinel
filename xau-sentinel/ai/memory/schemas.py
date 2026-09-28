"""Pydantic contracts for the trading memory layer — mirrors
ai/knowledge/schemas.py's convention: typed shapes for what store.py/
retrieval.py already produce, never a place new data gets invented.

Critically, MemoryCreateIn and MemoryUpdateIn have no `source` field — the
client can never set or override it (see ai/memory/store.py::create_memory,
which always writes "user_confirmed" itself).
"""
from typing import Optional

from pydantic import BaseModel

from ai.memory.models import MemoryCategory


class MemoryRecordOut(BaseModel):
    id: int
    category: MemoryCategory
    content: str
    source: str
    status: str
    created_at: str
    updated_at: str
    strategy_version: Optional[str] = None


class MemoryCreateIn(BaseModel):
    category: MemoryCategory
    content: str
    strategy_version: Optional[str] = None


class MemoryUpdateIn(BaseModel):
    content: Optional[str] = None
    category: Optional[MemoryCategory] = None
    strategy_version: Optional[str] = None


class MemoryUsedOut(BaseModel):
    """One memory record referenced for a chat turn — the UI's "Memory
    referenced" transparency panel renders this list directly, mirroring
    KnowledgeSourceOut."""
    id: int
    category: MemoryCategory
    excerpt: str
    similarity: float
    updated_at: str
