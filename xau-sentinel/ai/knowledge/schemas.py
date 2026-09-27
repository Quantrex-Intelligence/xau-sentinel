"""Pydantic contract for the knowledge layer — mirrors api/schemas.py's own
convention: a typed shape for what retrieval.py already produces, never a
place where new data gets invented."""
from pydantic import BaseModel


class KnowledgeSourceOut(BaseModel):
    source: str
    category: str
    version: str
    title: str
    similarity: float
    excerpt: str


class KnowledgeDocumentOut(BaseModel):
    id: int
    source: str
    category: str
    version: str
    title: str
    is_active: bool
    created_at: str
