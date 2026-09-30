"""PostgreSQL persistence for the trading memory layer (DEP-002). Table is
defined in journal/schema.py alongside every other table; this module only
builds and executes Core queries against it through
journal.database.get_connection().

Lifecycle is CREATE / READ / UPDATE / ARCHIVE only — there is no delete
function in this module, by design (the spec: "Do not hard-delete historical
memory by default"). An archived record stays in the table forever, just
excluded from normal listing/retrieval.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, insert, update

from journal.database import get_connection
from journal.schema import memory_records
from ai.knowledge.embeddings import BaseEmbeddingProvider, get_embedding_provider
from ai.memory.models import MemoryCategory, MemoryRecord, MemoryStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_record(row) -> MemoryRecord:
    return MemoryRecord(
        id=row.id, category=MemoryCategory(row.category), content=row.content,
        source=row.source, status=MemoryStatus(row.status),
        created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat(),
        strategy_version=row.strategy_version,
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
        result = conn.execute(
            insert(memory_records)
            .values(
                category=category.value, content=content, embedding=json.dumps(embedding),
                source="user_confirmed", strategy_version=strategy_version,
                status="ACTIVE", created_at=now, updated_at=now,
            )
            .returning(memory_records.c.id)
        )
        memory_id = result.scalar_one()
        conn.commit()
    return get_memory(memory_id)


def get_memory(memory_id: int) -> Optional[MemoryRecord]:
    with get_connection() as conn:
        row = conn.execute(select(memory_records).where(memory_records.c.id == memory_id)).fetchone()
    return _row_to_record(row) if row else None


def list_memories(category: Optional[MemoryCategory] = None, include_archived: bool = False) -> List[MemoryRecord]:
    query = select(memory_records)
    if not include_archived:
        query = query.where(memory_records.c.status == "ACTIVE")
    if category is not None:
        query = query.where(memory_records.c.category == category.value)
    query = query.order_by(memory_records.c.updated_at.desc())
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
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
                select(memory_records.c.embedding).where(memory_records.c.id == memory_id)
            ).scalar_one()

    with get_connection() as conn:
        conn.execute(
            update(memory_records)
            .where(memory_records.c.id == memory_id)
            .values(
                content=new_content, category=new_category.value, strategy_version=new_strategy_version,
                embedding=embedding_json, updated_at=_now(),
            )
        )
        conn.commit()
    return get_memory(memory_id)


def archive_memory(memory_id: int) -> Optional[MemoryRecord]:
    existing = get_memory(memory_id)
    if existing is None:
        return None
    with get_connection() as conn:
        conn.execute(
            update(memory_records)
            .where(memory_records.c.id == memory_id)
            .values(status="ARCHIVED", updated_at=_now())
        )
        conn.commit()
    return get_memory(memory_id)


def list_active_with_embeddings(categories: Optional[List[str]] = None) -> List[dict]:
    """Every ACTIVE record's embedding + metadata — exactly what
    retrieval.py needs for scoring, with no second lookup."""
    query = select(memory_records).where(memory_records.c.status == "ACTIVE")
    if categories:
        query = query.where(memory_records.c.category.in_(categories))

    with get_connection() as conn:
        rows = conn.execute(query).fetchall()

    return [
        {
            "id": r.id, "category": r.category, "content": r.content,
            "embedding": json.loads(r.embedding), "strategy_version": r.strategy_version,
            "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]
