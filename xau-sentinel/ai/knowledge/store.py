"""PostgreSQL persistence for the knowledge/RAG layer (DEP-002). Tables are
defined in journal/schema.py alongside every other table; this module only
builds and executes Core queries against them through
journal.database.get_connection().
"""
import json
from typing import List, Optional

from sqlalchemy import select, insert, update, func

from journal.database import get_connection
from journal.schema import knowledge_documents, knowledge_chunks
from ai.knowledge.chunking import chunk_text
from ai.knowledge.embeddings import BaseEmbeddingProvider, get_embedding_provider
from ai.knowledge.models import KnowledgeDocument


def add_document(source: str, category: str, version: str, title: str, content: str,
                  embedding_provider: Optional[BaseEmbeddingProvider] = None) -> int:
    """Deactivates any prior active version of this `source` (versioning:
    only one active version per source at a time — see Stage 5 plan), then
    chunks + embeds `content` and inserts a new document + its chunks.
    Returns the new document's id. A document with no extractable chunks
    (empty content) is still recorded, just with zero chunks — retrieval
    naturally never returns anything from it."""
    provider = embedding_provider or get_embedding_provider()
    chunks_text = chunk_text(content)
    embeddings = provider.embed(chunks_text) if chunks_text else []

    with get_connection() as conn:
        conn.execute(
            update(knowledge_documents)
            .where(knowledge_documents.c.source == source, knowledge_documents.c.is_active.is_(True))
            .values(is_active=False)
        )
        result = conn.execute(
            insert(knowledge_documents)
            .values(source=source, category=category, version=version, title=title, is_active=True)
            .returning(knowledge_documents.c.id)
        )
        document_id = result.scalar_one()
        for i, (chunk, emb) in enumerate(zip(chunks_text, embeddings)):
            conn.execute(
                insert(knowledge_chunks).values(
                    document_id=document_id, chunk_index=i, text=chunk, embedding=json.dumps(emb),
                )
            )
        conn.commit()
    return document_id


def list_documents(active_only: bool = True) -> List[KnowledgeDocument]:
    query = select(knowledge_documents)
    if active_only:
        query = query.where(knowledge_documents.c.is_active.is_(True))
    query = query.order_by(knowledge_documents.c.category, knowledge_documents.c.source)
    with get_connection() as conn:
        rows = conn.execute(query).mappings().fetchall()
    return [
        KnowledgeDocument(
            id=r["id"], source=r["source"], category=r["category"], version=r["version"],
            title=r["title"], is_active=r["is_active"], created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


def get_active_chunks(categories: Optional[List[str]] = None) -> List[dict]:
    """Every chunk belonging to a currently-active document, each carrying
    its parent document's metadata (source/category/version/title) —
    exactly what retrieval.py needs for scoring and source attribution,
    with no second lookup."""
    query = (
        select(
            knowledge_chunks.c.id.label("chunk_id"), knowledge_chunks.c.document_id,
            knowledge_chunks.c.chunk_index, knowledge_chunks.c.text, knowledge_chunks.c.embedding,
            knowledge_documents.c.source, knowledge_documents.c.category,
            knowledge_documents.c.version, knowledge_documents.c.title,
        )
        .select_from(knowledge_chunks.join(knowledge_documents, knowledge_documents.c.id == knowledge_chunks.c.document_id))
        .where(knowledge_documents.c.is_active.is_(True))
    )
    if categories:
        query = query.where(knowledge_documents.c.category.in_(categories))

    with get_connection() as conn:
        rows = conn.execute(query).mappings().fetchall()

    return [
        {
            "chunk_id": r["chunk_id"], "document_id": r["document_id"], "chunk_index": r["chunk_index"],
            "text": r["text"], "embedding": json.loads(r["embedding"]),
            "source": r["source"], "category": r["category"], "version": r["version"], "title": r["title"],
        }
        for r in rows
    ]


def count_documents(active_only: bool = True) -> int:
    query = select(func.count()).select_from(knowledge_documents)
    if active_only:
        query = query.where(knowledge_documents.c.is_active.is_(True))
    with get_connection() as conn:
        return conn.execute(query).scalar_one()
