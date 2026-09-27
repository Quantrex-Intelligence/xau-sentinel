"""SQLite persistence for the knowledge/RAG layer. Two new tables, added the
established way: CREATE TABLE IF NOT EXISTS through
journal.database.get_connection() (calling it, never editing it) — same
pattern as risk/fundednext_journal.py and ai/assistant.py's ai_messages
table. The frozen Stage 1 schema in journal/database.py is never touched.
"""
import json
import sqlite3
from typing import List, Optional

from journal.database import get_connection
from ai.knowledge.chunking import chunk_text
from ai.knowledge.embeddings import BaseEmbeddingProvider, get_embedding_provider
from ai.knowledge.models import KnowledgeDocument

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


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
            "UPDATE knowledge_documents SET is_active = 0 WHERE source = ? AND is_active = 1",
            (source,),
        )
        cur = conn.execute(
            "INSERT INTO knowledge_documents (source, category, version, title, is_active) VALUES (?, ?, ?, ?, 1)",
            (source, category, version, title),
        )
        document_id = cur.lastrowid
        for i, (chunk, emb) in enumerate(zip(chunks_text, embeddings)):
            conn.execute(
                "INSERT INTO knowledge_chunks (document_id, chunk_index, text, embedding) VALUES (?, ?, ?, ?)",
                (document_id, i, chunk, json.dumps(emb)),
            )
        conn.commit()
    return document_id


def list_documents(active_only: bool = True) -> List[KnowledgeDocument]:
    query = "SELECT * FROM knowledge_documents"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY category, source"
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [
        KnowledgeDocument(
            id=r["id"], source=r["source"], category=r["category"], version=r["version"],
            title=r["title"], is_active=bool(r["is_active"]), created_at=r["created_at"],
        )
        for r in rows
    ]


def get_active_chunks(categories: Optional[List[str]] = None) -> List[dict]:
    """Every chunk belonging to a currently-active document, each carrying
    its parent document's metadata (source/category/version/title) —
    exactly what retrieval.py needs for scoring and source attribution,
    with no second lookup."""
    query = """
        SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.text, c.embedding,
               d.source, d.category, d.version, d.title
        FROM knowledge_chunks c
        JOIN knowledge_documents d ON d.id = c.document_id
        WHERE d.is_active = 1
    """
    params: list = []
    if categories:
        placeholders = ", ".join("?" for _ in categories)
        query += f" AND d.category IN ({placeholders})"
        params.extend(categories)

    try:
        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError as exc:
        # A caller that never ran init_table() against this DB (e.g. the
        # app hasn't started yet, or a test predating Stage 5) genuinely
        # has no knowledge stored — identical in effect to an empty
        # knowledge base, so this degrades the same way rather than
        # crashing every caller of retrieve().
        if "no such table" in str(exc):
            return []
        raise

    return [
        {
            "chunk_id": r["chunk_id"], "document_id": r["document_id"], "chunk_index": r["chunk_index"],
            "text": r["text"], "embedding": json.loads(r["embedding"]),
            "source": r["source"], "category": r["category"], "version": r["version"], "title": r["title"],
        }
        for r in rows
    ]


def count_documents(active_only: bool = True) -> int:
    query = "SELECT COUNT(*) AS n FROM knowledge_documents"
    if active_only:
        query += " WHERE is_active = 1"
    with get_connection() as conn:
        return conn.execute(query).fetchone()["n"]
