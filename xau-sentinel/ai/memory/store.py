"""SQLite persistence for the trading memory layer. One new table, added the
established way: CREATE TABLE IF NOT EXISTS through
journal.database.get_connection() (calling it, never editing it) — same
pattern as ai/knowledge/store.py, risk/fundednext_journal.py, and
ai/assistant.py's ai_messages table. The frozen Stage 1 schema in
journal/database.py is never touched.

Lifecycle is CREATE / READ / UPDATE / ARCHIVE only — there is no delete
function in this module, by design (the spec: "Do not hard-delete historical
memory by default"). An archived record stays in the table forever, just
excluded from normal listing/retrieval.
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from journal.database import get_connection
from ai.knowledge.embeddings import BaseEmbeddingProvider, get_embedding_provider
from ai.memory.models import MemoryCategory, MemoryRecord, MemoryStatus

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding TEXT NOT NULL,
    source TEXT NOT NULL,
    strategy_version TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def _row_to_record(row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"], category=MemoryCategory(row["category"]), content=row["content"],
        source=row["source"], status=MemoryStatus(row["status"]),
        created_at=row["created_at"], updated_at=row["updated_at"],
        strategy_version=row["strategy_version"],
    )


def create_memory(category: MemoryCategory, content: str, strategy_version: Optional[str] = None,
                   embedding_provider: Optional[BaseEmbeddingProvider] = None) -> MemoryRecord:
    """The only write entry point for a NEW memory. `source` is always
    "user_confirmed" — hardcoded here, never accepted as a parameter from a
    caller, so there is no way for any other code path (a tool, the LLM's
    own reply, a prompt-injected instruction) to produce a memory record
    claiming a different provenance. The only caller of this function in the
    whole codebase is api/routes/memory.py's POST handler, invoked by an
    explicit user action."""
    provider = embedding_provider or get_embedding_provider()
    embedding = provider.embed_one(content)
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO memory_records (category, content, embedding, source, strategy_version,
                                            status, created_at, updated_at)
               VALUES (?, ?, ?, 'user_confirmed', ?, 'ACTIVE', ?, ?)""",
            (category.value, content, json.dumps(embedding), strategy_version, now, now),
        )
        memory_id = cur.lastrowid
        conn.commit()
    return get_memory(memory_id)


def get_memory(memory_id: int) -> Optional[MemoryRecord]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
    return _row_to_record(row) if row else None


def list_memories(category: Optional[MemoryCategory] = None, include_archived: bool = False) -> List[MemoryRecord]:
    query = "SELECT * FROM memory_records WHERE 1=1"
    params: list = []
    if not include_archived:
        query += " AND status = 'ACTIVE'"
    if category is not None:
        query += " AND category = ?"
        params.append(category.value)
    query += " ORDER BY updated_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_record(r) for r in rows]


def update_memory(memory_id: int, content: Optional[str] = None, category: Optional[MemoryCategory] = None,
                   strategy_version: Optional[str] = None,
                   embedding_provider: Optional[BaseEmbeddingProvider] = None) -> Optional[MemoryRecord]:
    """Updates only the fields given; content changes re-embed. Never
    touches `source` or `status` — archiving is a separate, explicit action
    (see archive_memory)."""
    existing = get_memory(memory_id)
    if existing is None:
        return None

    new_content = content if content is not None else existing.content
    new_category = category if category is not None else existing.category
    new_strategy_version = strategy_version if strategy_version is not None else existing.strategy_version

    if content is not None and content != existing.content:
        provider = embedding_provider or get_embedding_provider()
        embedding_json = json.dumps(provider.embed_one(new_content))
    else:
        with get_connection() as conn:
            embedding_json = conn.execute(
                "SELECT embedding FROM memory_records WHERE id = ?", (memory_id,)
            ).fetchone()["embedding"]

    with get_connection() as conn:
        conn.execute(
            """UPDATE memory_records
               SET content = ?, category = ?, strategy_version = ?, embedding = ?, updated_at = ?
               WHERE id = ?""",
            (new_content, new_category.value, new_strategy_version, embedding_json, _now(), memory_id),
        )
        conn.commit()
    return get_memory(memory_id)


def archive_memory(memory_id: int) -> Optional[MemoryRecord]:
    existing = get_memory(memory_id)
    if existing is None:
        return None
    with get_connection() as conn:
        conn.execute(
            "UPDATE memory_records SET status = 'ARCHIVED', updated_at = ? WHERE id = ?",
            (_now(), memory_id),
        )
        conn.commit()
    return get_memory(memory_id)


def list_active_with_embeddings(categories: Optional[List[str]] = None) -> List[dict]:
    """Every ACTIVE record's embedding + metadata — exactly what
    retrieval.py needs for scoring, with no second lookup. Degrades to []
    if the table doesn't exist yet (a caller that never ran init_table()
    against this DB), the same way ai/knowledge/store.py's
    get_active_chunks() already does — a missing table is semantically an
    empty memory store, not an error."""
    query = "SELECT * FROM memory_records WHERE status = 'ACTIVE'"
    params: list = []
    if categories:
        placeholders = ", ".join("?" for _ in categories)
        query += f" AND category IN ({placeholders})"
        params.extend(categories)

    try:
        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise

    return [
        {
            "id": r["id"], "category": r["category"], "content": r["content"],
            "embedding": json.loads(r["embedding"]), "strategy_version": r["strategy_version"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
        for r in rows
    ]
