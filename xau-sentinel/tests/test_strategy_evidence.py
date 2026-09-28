"""Tests for ai/strategy/evidence.py — the Evidence Builder. Covers
relevance decisions (constructed directly, not dependent on mock
randomness), independent degradation of each evidence source, and that
every section renderer is pure Python (never calls an LLM)."""
import inspect

from ai.knowledge.models import RetrievedChunk
from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot, MarketIntelligenceContext, NewsArticle,
)
from ai.memory.models import MemoryCategory, RetrievedMemory
from ai.similarity.models import MatchedSetup, Outcome, SetupFeatures, SimilarityResult
from ai.strategy import evidence as evidence_mod
from ai.strategy.evidence import ContextualEvidence, build_contextual_evidence
from ai.strategy.schemas import FundedNextGateOut, Rating, StrategyEvaluationOut


def _result(**overrides):
    base = dict(
        rating=Rating.DEVELOPING, direction="BUY", criteria=[], context_evidence=[],
        missing_conditions=["Retracement"], fundednext=FundedNextGateOut(
            data_available=True, safety_level="SAFE", daily_loss_used_pct=10.0,
            max_daily_loss_used_pct_allowed=50.0, reason="SAFE",
        ),
        evaluated_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return StrategyEvaluationOut(**base)


# ---------------------------------------------------------------------------
# Relevance decisions — constructed evidence, not dependent on mock randomness
# ---------------------------------------------------------------------------

def _mi(events=None, news=None, macro_available=True, cross_asset_available=True):
    return MarketIntelligenceContext(
        data_available=True, generated_at="2026-01-01T00:00:00+00:00",
        macro=MacroSnapshot(data_available=macro_available, source="mock", fed_funds_rate=5.25,
                             cpi_yoy=3.0, us10y_yield=4.2) if macro_available else None,
        gold_fundamentals=GoldFundamentals(data_available=True, source="mock"),
        cross_asset=CrossAssetSnapshot(data_available=cross_asset_available, source="mock",
                                        dxy=104.0, us10y_yield=4.2, vix=15.0) if cross_asset_available else None,
        events=events or [], news=news or [], sources=["mock"],
    )


def test_market_intelligence_not_relevant_with_no_high_events_and_no_news():
    mi = _mi(events=[
        EconomicEvent(name="Low importance event", category="Growth", importance="LOW",
                       scheduled_at="2026-01-02T00:00:00+00:00", source="mock"),
    ], news=[])
    assert evidence_mod._is_market_intelligence_relevant(mi) is False


def test_market_intelligence_relevant_with_a_high_importance_event():
    mi = _mi(events=[
        EconomicEvent(name="US CPI", category="Inflation", importance="HIGH",
                       scheduled_at="2026-01-02T00:00:00+00:00", source="mock"),
    ], news=[])
    assert evidence_mod._is_market_intelligence_relevant(mi) is True


def test_market_intelligence_relevant_with_news_even_without_high_events():
    mi = _mi(events=[], news=[
        NewsArticle(id="1", headline="Gold steadies", source="wire", published_at="2026-01-01T00:00:00+00:00",
                    retrieved_at="2026-01-01T00:00:00+00:00"),
    ])
    assert evidence_mod._is_market_intelligence_relevant(mi) is True


def test_market_intelligence_not_relevant_when_none():
    assert evidence_mod._is_market_intelligence_relevant(None) is False


# ---------------------------------------------------------------------------
# build_contextual_evidence: independent degradation per source
# ---------------------------------------------------------------------------

def test_build_contextual_evidence_degrades_when_market_intelligence_fails(monkeypatch, temp_db):
    def _boom():
        raise RuntimeError("simulated MI outage")
    monkeypatch.setattr(evidence_mod.mi_context, "build_market_intelligence_context", _boom)

    result = _result()
    evidence = build_contextual_evidence(result)

    assert evidence.market_intelligence is None
    assert evidence.market_intelligence_relevant is False
    # Reaching this line at all proves the MI failure never propagated as an
    # exception up through build_contextual_evidence().


def test_build_contextual_evidence_degrades_when_similarity_fails(monkeypatch, temp_db):
    def _boom(*_a, **_kw):
        raise RuntimeError("simulated similarity outage")
    monkeypatch.setattr(evidence_mod.similarity_engine, "resolve_query_features", _boom)

    result = _result()
    evidence = build_contextual_evidence(result)

    assert evidence.similarity is None
    assert evidence.similarity_relevant is False


def test_build_contextual_evidence_degrades_when_knowledge_retrieval_fails(monkeypatch, temp_db):
    def _boom(*_a, **_kw):
        raise RuntimeError("simulated RAG outage")
    monkeypatch.setattr(evidence_mod.knowledge_retrieval, "retrieve", _boom)

    result = _result()
    evidence = build_contextual_evidence(result)

    assert evidence.knowledge_chunks == []


def test_build_contextual_evidence_degrades_when_memory_retrieval_fails(monkeypatch, temp_db):
    def _boom(*_a, **_kw):
        raise RuntimeError("simulated memory outage")
    monkeypatch.setattr(evidence_mod.memory_retrieval, "retrieve_memory", _boom)

    result = _result()
    evidence = build_contextual_evidence(result)

    assert evidence.memory == []


def test_build_contextual_evidence_with_everything_unavailable_still_returns_an_object(monkeypatch, temp_db):
    def _boom(*_a, **_kw):
        raise RuntimeError("simulated total outage")
    monkeypatch.setattr(evidence_mod.mi_context, "build_market_intelligence_context", _boom)
    monkeypatch.setattr(evidence_mod.similarity_engine, "resolve_query_features", _boom)
    monkeypatch.setattr(evidence_mod.knowledge_retrieval, "retrieve", _boom)
    monkeypatch.setattr(evidence_mod.memory_retrieval, "retrieve_memory", _boom)

    evidence = build_contextual_evidence(_result())

    assert evidence == ContextualEvidence()


# ---------------------------------------------------------------------------
# Deterministic section renderers never call an LLM
# ---------------------------------------------------------------------------

def test_renderer_functions_never_call_an_llm_provider():
    for fn in (
        evidence_mod.technical_summary, evidence_mod.strategy_summary, evidence_mod.risk_context,
        evidence_mod.market_intelligence_summary, evidence_mod.historical_context, evidence_mod.uncertainties,
        evidence_mod.render_for_llm,
    ):
        source = inspect.getsource(fn)
        assert "get_provider" not in source
        assert ".chat(" not in source


def test_technical_summary_uses_context_evidence_verbatim():
    result = _result(context_evidence=["H4 bias: BULLISH — trending", "M15 bias: PULLBACK — retracing"])
    assert evidence_mod.technical_summary(result) == "H4 bias: BULLISH — trending M15 bias: PULLBACK — retracing"


def test_strategy_summary_includes_missing_conditions_and_invalidation():
    result = _result(missing_conditions=["Retracement", "Minimum R:R"], invalidation="Expired")
    summary = evidence_mod.strategy_summary(result)
    assert "Missing: Retracement, Minimum R:R." in summary
    assert "Invalidation: Expired" in summary


def test_risk_context_reports_unavailable_fundednext_without_fabricating():
    result = _result(fundednext=FundedNextGateOut(
        data_available=False, max_daily_loss_used_pct_allowed=50.0, reason="MT5 not connected",
    ))
    text = evidence_mod.risk_context(result)
    assert "unavailable" in text.lower()
    assert "MT5 not connected" in text


def test_market_intelligence_summary_relevant_false_when_not_relevant():
    evidence = ContextualEvidence(market_intelligence=_mi(events=[], news=[]), market_intelligence_relevant=False)
    summary = evidence_mod.market_intelligence_summary(evidence)
    assert summary.relevant is False
    assert summary.macro is None
    assert summary.events is None
    assert summary.news is None


def test_market_intelligence_summary_populates_fields_when_relevant():
    mi = _mi(events=[EconomicEvent(name="US CPI", category="Inflation", importance="HIGH",
                                    scheduled_at="2026-01-02T00:00:00+00:00", source="mock")],
              news=[NewsArticle(id="1", headline="Gold steadies", source="wire",
                                 published_at="2026-01-01T00:00:00+00:00",
                                 retrieved_at="2026-01-01T00:00:00+00:00")])
    evidence = ContextualEvidence(market_intelligence=mi, market_intelligence_relevant=True)
    summary = evidence_mod.market_intelligence_summary(evidence)
    assert summary.relevant is True
    assert "5.25" in summary.macro
    assert "US CPI" in summary.events
    assert "Gold steadies" in summary.news


def test_historical_context_says_limited_when_no_matches():
    evidence = ContextualEvidence(similarity=SimilarityResult(matches=[]), similarity_relevant=False)
    text = evidence_mod.historical_context(evidence)
    assert "limited" in text.lower()
    assert "Descriptive only" in text
    assert "%" not in text  # no fabricated similarity percentage when there's nothing to compute one from


def test_historical_context_lists_matches_and_stays_descriptive():
    match = MatchedSetup(
        trade_id=183, similarity=0.87, entry_snapshot=SetupFeatures(),
        outcome=Outcome(status="CLOSED", result="WIN"), matched_features=["h1_structure"], different_features=[],
    )
    evidence = ContextualEvidence(similarity=SimilarityResult(matches=[match]), similarity_relevant=True)
    text = evidence_mod.historical_context(evidence)
    assert "Trade #183" in text
    assert "87%" in text
    assert "WIN" in text
    assert "Descriptive only — not a prediction" in text
    assert "chance" not in text.lower()
    assert "probability" not in text.lower()


def test_uncertainties_includes_missing_conditions_and_evidence_gaps():
    result = _result(missing_conditions=["Retracement"])
    evidence = ContextualEvidence(market_intelligence_relevant=False, similarity_relevant=False,
                                   knowledge_chunks=[], memory=[])
    items = evidence_mod.uncertainties(result, evidence)
    assert "Retracement" in items
    assert any("macro" in i.lower() for i in items)
    assert any("historical similarity" in i.lower() for i in items)
    assert any("strategy documentation" in i.lower() for i in items)
    assert any("preferences or lessons" in i.lower() for i in items)


def test_uncertainties_omits_gaps_that_are_actually_filled():
    result = _result(missing_conditions=[])
    chunk = RetrievedChunk(text="x", similarity=0.5, document_id=1, source="s", category="c",
                            version="1.0", title="t", chunk_index=0)
    mem = RetrievedMemory(id=1, category=MemoryCategory.TRADE_LESSON, content="x", similarity=0.5,
                           created_at="2026-01-01", updated_at="2026-01-01")
    evidence = ContextualEvidence(market_intelligence_relevant=True, similarity_relevant=True,
                                   knowledge_chunks=[chunk], memory=[mem])
    assert evidence_mod.uncertainties(result, evidence) == []


def test_render_for_llm_marks_market_intelligence_not_relevant_when_absent():
    evidence = ContextualEvidence(market_intelligence_relevant=False, similarity_relevant=False)
    text = evidence_mod.render_for_llm(evidence)
    assert "Market Intelligence: not materially relevant right now." in text
    assert "Historical similarity: limited" in text
