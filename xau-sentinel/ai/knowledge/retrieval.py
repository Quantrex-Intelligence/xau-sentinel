"""Retrieval over the active knowledge base: embed the query, score every
active chunk by cosine similarity, return the top-K above a minimum
threshold. Brute-force in Python — no vector index — appropriate at this
scale (a small, local knowledge base), matching "avoid unnecessary
infrastructure" from the Stage 5 spec.

Never touches live market/account/journal data — those come only from
api/snapshot.py, risk/fundednext.py, and journal/trades.py via
ai/context.py, entirely independent of this module. Retrieval only ever
returns *reference* text, never a live fact.
"""
from typing import List, Optional

import config
from ai.knowledge import store
from ai.knowledge.embeddings import cosine_similarity, get_embedding_provider
from ai.knowledge.models import RetrievedChunk


def retrieve(query: str, top_k: Optional[int] = None, min_similarity: Optional[float] = None,
             categories: Optional[List[str]] = None) -> List[RetrievedChunk]:
    """Returns [] — an explicit no-match — when the query is blank, the
    knowledge base is empty, or nothing clears the similarity threshold.
    Never a fabricated or best-effort-anyway result."""
    if not query or not query.strip():
        return []

    top_k = top_k if top_k is not None else config.AI_KNOWLEDGE_TOP_K
    min_similarity = min_similarity if min_similarity is not None else config.AI_KNOWLEDGE_MIN_SIMILARITY

    chunks = store.get_active_chunks(categories)
    if not chunks:
        return []

    provider = get_embedding_provider()
    query_embedding = provider.embed_one(query)

    scored = []
    for c in chunks:
        score = cosine_similarity(query_embedding, c["embedding"])
        if score >= min_similarity:
            scored.append((score, c))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        RetrievedChunk(
            text=c["text"], similarity=round(score, 4), document_id=c["document_id"],
            source=c["source"], category=c["category"], version=c["version"],
            title=c["title"], chunk_index=c["chunk_index"],
        )
        for score, c in scored[:top_k]
    ]
