"""Data shapes for the knowledge/RAG layer. Pure data — no retrieval or
storage logic lives here."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class KnowledgeDocument:
    id: int
    source: str        # e.g. "ai/strategy/rules.py", "README.md", "user_notes"
    category: str       # "strategy_rules" | "strategy_docs" | "methodology" | "fundednext_rules" | "system_docs" | "user_notes"
    version: str
    title: str
    is_active: bool
    created_at: str


@dataclass
class KnowledgeChunk:
    id: int
    document_id: int
    chunk_index: int
    text: str
    embedding: list[float]


@dataclass
class RetrievedChunk:
    """One chunk returned by retrieval, carrying enough of its parent
    document's metadata for source attribution — the UI and the prompt
    both need source/category/version without a second lookup."""
    text: str
    similarity: float
    document_id: int
    source: str
    category: str
    version: str
    title: str
    chunk_index: int
