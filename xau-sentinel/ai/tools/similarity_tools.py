"""Read-only tool wrapper over ai.similarity — find_similar_setups is
DESCRIPTIVE feature comparison, never a win-probability estimate (see
ai/similarity/scoring.py). The tool's own description carries that framing
to the model, alongside ai/prompts.py's ground rule 9 and the deterministic
contains_predictive_probability_claim() backstop applied to every final
answer regardless of what provoked it."""
from dataclasses import asdict
from datetime import datetime, timezone

from ai.similarity import engine
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult


def find_similar_setups(args: dict) -> ToolResult:
    trade_id = args.get("trade_id")
    top_k = args.get("top_k")
    min_similarity = args.get("min_similarity")

    query_features, exclude_trade_id = engine.resolve_query_features(trade_id)
    if query_features is None:
        reason = (
            f"No trade with id {trade_id}." if trade_id is not None
            else "No current setup data available to compare against."
        )
        return ToolResult(data_available=False, reason=reason, source="ai.similarity")

    result = engine.find_similar_setups(
        query_features, exclude_trade_id=exclude_trade_id, top_k=top_k, min_similarity=min_similarity,
    )
    return ToolResult(
        data_available=True, timestamp=datetime.now(timezone.utc).isoformat(), source="ai.similarity",
        data={
            "query_features": asdict(query_features),
            "matches": [
                {
                    "trade_id": m.trade_id, "similarity": m.similarity,
                    "entry_snapshot": asdict(m.entry_snapshot), "outcome": asdict(m.outcome),
                    "matched_features": m.matched_features, "different_features": m.different_features,
                }
                for m in result.matches
            ],
            "considered_count": result.considered_count,
            "excluded_count": result.excluded_count,
        },
    )


register(ToolSpec(
    "find_similar_setups", "Historical Setup Similarity",
    "Compare the current candidate setup (or a specific past trade by id) against historical journal "
    "trades using a deterministic, weighted feature match. Returns feature SIMILARITY only — never a win "
    "probability or outcome prediction. Past outcomes shown alongside a match describe what happened, "
    "they do not forecast what will happen this time.",
    {"type": "object", "properties": {
        "trade_id": {"type": "integer"},
        "top_k": {"type": "integer"},
        "min_similarity": {"type": "number"},
    }},
    find_similar_setups,
))
