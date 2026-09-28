"""Retrieval over ACTIVE trading memory — a layer separate from
ai/knowledge/retrieval.py (Stage 5's RAG over project documentation), even
though both reuse the same embedding utilities (ai.knowledge.embeddings) to
avoid building a second embedding stack for no reason. Brute-force cosine
scoring, same shape as Stage 5: never retrieve everything, never force a
match, top-K above a minimum threshold.

Archived memories are structurally excluded — store.list_active_with_embeddings()
only ever returns ACTIVE rows, so there's no caller-side filter to forget.
"""
from typing import List, Optional

import config
from ai.knowledge.embeddings import cosine_similarity, get_embedding_provider
from ai.memory import store
from ai.memory.models import MemoryCategory, RetrievedMemory


def retrieve_memory(query: str, top_k: Optional[int] = None, min_similarity: Optional[float] = None,
                     categories: Optional[List[str]] = None) -> List[RetrievedMemory]:
    """Returns [] — an explicit no-match — when the query is blank, no
    memory exists yet, or nothing clears the similarity threshold. Never a
    fabricated or best-effort-anyway result. Conflicting memories (e.g. two
    records that disagree) are never deduplicated or resolved here — both
    are returned, ranked by similarity, for the prompt to surface rather
    than silently reconcile (see ai/prompts.py ground rule 8)."""
    if not query or not query.strip():
        return []

    top_k = top_k if top_k is not None else config.AI_MEMORY_TOP_K
    min_similarity = min_similarity if min_similarity is not None else config.AI_MEMORY_MIN_SIMILARITY

    records = store.list_active_with_embeddings(categories)
    if not records:
        return []

    provider = get_embedding_provider()
    query_embedding = provider.embed_one(query)

    scored = []
    for r in records:
        score = cosine_similarity(query_embedding, r["embedding"])
        if score >= min_similarity:
            scored.append((score, r))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        RetrievedMemory(
            id=r["id"], category=MemoryCategory(r["category"]), content=r["content"],
            similarity=round(score, 4), created_at=r["created_at"], updated_at=r["updated_at"],
            strategy_version=r["strategy_version"],
        )
        for score, r in scored[:top_k]
    ]
