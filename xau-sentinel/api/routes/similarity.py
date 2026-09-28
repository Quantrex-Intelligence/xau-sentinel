"""Historical setup similarity routes — read-only, descriptive feature
comparison against journal trades. Every handler is a thin call into
ai.similarity.engine; no scoring or extraction logic lives here. Mirrors
how /api/strategy/aplus gives the UI a direct data source alongside the
assistant's equivalent tool (ai/tools/similarity_tools.py)."""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ai.similarity import engine
from ai.similarity.schemas import (
    OutcomeOut, SetupFeaturesOut, SimilarityResultOut, SimilarSetupOut,
)

router = APIRouter(prefix="/api/similarity", tags=["similarity"])


def _result_out(query_features, result) -> SimilarityResultOut:
    return SimilarityResultOut(
        query_features=SetupFeaturesOut(**asdict(query_features)),
        matches=[
            SimilarSetupOut(
                trade_id=m.trade_id, similarity=m.similarity,
                entry_snapshot=SetupFeaturesOut(**asdict(m.entry_snapshot)),
                outcome=OutcomeOut(**asdict(m.outcome)),
                matched_features=m.matched_features, different_features=m.different_features,
            )
            for m in result.matches
        ],
        considered_count=result.considered_count, excluded_count=result.excluded_count,
    )


@router.get("/current", response_model=SimilarityResultOut)
def get_current_similarity(top_k: int | None = None, min_similarity: float | None = None):
    query_features, exclude_id = engine.resolve_query_features(None)
    if query_features is None:
        raise HTTPException(status_code=503, detail="No current setup data available to compare against.")
    result = engine.find_similar_setups(query_features, exclude_id, top_k, min_similarity)
    return _result_out(query_features, result)


@router.get("/trade/{trade_id}", response_model=SimilarityResultOut)
def get_trade_similarity(trade_id: int, top_k: int | None = None, min_similarity: float | None = None):
    query_features, exclude_id = engine.resolve_query_features(trade_id)
    if query_features is None:
        raise HTTPException(status_code=404, detail=f"No trade with id {trade_id}.")
    result = engine.find_similar_setups(query_features, exclude_id, top_k, min_similarity)
    return _result_out(query_features, result)
