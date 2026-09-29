"""Tests for ai/trade_review/engine.py — build_trade_review() uses the
trade's own immutable fundednext_context snapshot, never live
compute_status(); it is deterministic-only (no LLM/network call)."""
import inspect

from ai.trade_review import engine
from ai.trade_review.models import Outcome, StrategyAlignment


def _trade(**overrides):
    defaults = dict(
        id=1, status="CLOSED", result="WIN", direction="BUY",
        h1_bias="BULLISH", liquidity="Previous Day Low swept", mss="Bullish", displacement="Bullish",
        planned_rr=3.0, r_multiple=3.0, duration_minutes=45,
    )
    defaults.update(overrides)
    return defaults


def test_build_trade_review_assembles_all_fields():
    review = engine.build_trade_review(_trade(), {"data_available": True, "safety_level": "SAFE"})
    assert review.trade_id == 1
    assert review.outcome == Outcome.WIN
    assert review.strategy_alignment == StrategyAlignment.ALIGNED
    assert review.setup_alignment == StrategyAlignment.ALIGNED
    assert review.execution_alignment == StrategyAlignment.ALIGNED
    assert review.risk_alignment == StrategyAlignment.ALIGNED
    assert review.deviations == []
    assert len(review.rule_observations) == 4


def test_build_trade_review_never_calls_the_llm_or_evidence_sources():
    """Structural: engine.py is deterministic-only — no LLM, no
    similarity/RAG/memory retrieval (those are only gathered at
    generate-review time, in ai/trade_review/service.py)."""
    source = inspect.getsource(engine)
    for banned in ("get_provider", ".chat(", "resolve_query_features", "knowledge_retrieval", "memory_retrieval"):
        assert banned not in source


def test_build_trade_review_uses_the_snapshot_argument_not_live_status():
    """Passing a CRITICAL snapshot must produce NOT_ALIGNED risk —
    proving the function uses exactly what it was given, never a live
    lookup of its own."""
    review = engine.build_trade_review(_trade(), {"data_available": True, "safety_level": "CRITICAL"})
    assert review.risk_alignment == StrategyAlignment.NOT_ALIGNED


def test_build_trade_review_handles_missing_snapshot_gracefully():
    review = engine.build_trade_review(_trade(), None)
    assert review.risk_alignment == StrategyAlignment.UNKNOWN


def test_build_trade_review_interpretation_is_none_before_generation():
    review = engine.build_trade_review(_trade(), None)
    assert review.interpretation is None
