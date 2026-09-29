"""Evidence gathering for the AI trade-review explanation step (Stage 16).
Reuses ai.strategy.evidence.ContextualEvidence again — the same "already
subject-agnostic" reuse ai/explanations/context.py found for Stage 15 —
and the exact same underlying calls Stage 15's trade-explanation path
already established: ai.similarity.engine (a specific trade_id, never the
live setup), ai.knowledge.retrieval, ai.memory.retrieval. Read-only:
nothing here ever writes a memory record or a knowledge document — saving
a lesson stays an explicit user action (see ai/memory/store.py::create_memory()'s
own "the only write entry point" guarantee, untouched by this stage).

Market Intelligence is never gathered here, for the same reason Stage 15
omits it for trade explanations: today's conditions describing a trade
that closed in the past would misleadingly conflate current data with
historical context.
"""
from typing import Any, Dict

from ai.knowledge import retrieval as knowledge_retrieval
from ai.memory import retrieval as memory_retrieval
from ai.similarity import engine as similarity_engine
from ai.strategy.evidence import ContextualEvidence


def _trade_query(trade: Dict[str, Any]) -> str:
    parts = [trade.get("direction") or "", trade.get("setup") or "", "trade review"]
    return " ".join(p for p in parts if p).strip()


def gather_evidence_for_trade(trade_id: int, trade: Dict[str, Any]) -> ContextualEvidence:
    evidence = ContextualEvidence()

    try:
        features, exclude_id = similarity_engine.resolve_query_features(trade_id)
        if features is not None:
            result = similarity_engine.find_similar_setups(features, exclude_trade_id=exclude_id)
            evidence.similarity = result
            evidence.similarity_relevant = len(result.matches) > 0
    except Exception:  # noqa: BLE001 - one evidence source failing must never break the others
        pass

    query = _trade_query(trade)
    try:
        evidence.knowledge_chunks = knowledge_retrieval.retrieve(query) if query else []
    except Exception:  # noqa: BLE001
        pass
    try:
        evidence.memory = memory_retrieval.retrieve_memory(query) if query else []
    except Exception:  # noqa: BLE001
        pass

    return evidence
