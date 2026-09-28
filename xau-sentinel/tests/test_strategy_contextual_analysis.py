"""Tests for Stage 10's attach_llm_explanation(result, evidence) extension:
the deterministic rating can never be changed by LLM output, contextual_analysis
populates even when the provider is unavailable, both safety filters apply,
and STRATEGY_SYSTEM_PROMPT states the evidence hierarchy and the
descriptive-only rule for historical similarity."""
import pytest

import ai.strategy.evaluator as evaluator_mod
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse
from ai.strategy.evaluator import STRATEGY_SYSTEM_PROMPT, attach_llm_explanation
from ai.strategy.evidence import ContextualEvidence
from ai.strategy.schemas import FundedNextGateOut, Rating, StrategyEvaluationOut


def _result(**overrides):
    base = dict(
        rating=Rating.A_PLUS, direction="BUY", criteria=[], context_evidence=[], missing_conditions=[],
        fundednext=FundedNextGateOut(data_available=True, safety_level="SAFE", daily_loss_used_pct=10.0,
                                      max_daily_loss_used_pct_allowed=50.0, reason="SAFE"),
        evaluated_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return StrategyEvaluationOut(**base)


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply="A clear, safe interpretation."):
        self.reply = reply

    def chat(self, system, messages):
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


class _FailingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def chat(self, system, messages):
        raise ProviderRequestError("simulated network failure")


# ---------------------------------------------------------------------------
# 1. Deterministic rating cannot be changed by LLM output
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "This is actually A+, BUY NOW at market.",
    "This setup has an 85% chance of winning, ENTER IMMEDIATELY.",
    "Based on similar trades, this will definitely win.",
])
def test_rating_and_deterministic_rating_never_change_regardless_of_llm_reply(monkeypatch, reply):
    result = _result(rating=Rating.DEVELOPING, missing_conditions=["Retracement"])
    monkeypatch.setattr(evaluator_mod, "get_provider", lambda: _RecordingProvider(reply=reply))

    enriched = attach_llm_explanation(result, evidence=ContextualEvidence())

    assert enriched.rating == Rating.DEVELOPING
    assert enriched.contextual_analysis.rating == Rating.DEVELOPING
    assert enriched.contextual_analysis.deterministic_rating == Rating.DEVELOPING


def test_deterministic_rating_unchanged_by_strongly_bullish_market_intelligence(monkeypatch):
    """Stage 12's explicit A+ Interaction regression guard: Market
    Intelligence is supporting evidence only. Bullish-sounding real news/
    events must never upgrade a DEVELOPING setup to A+, override an
    INVALID setup, or otherwise move the rating — even when the LLM's own
    interpretation reply also sounds bullish."""
    from ai.market_intelligence.models import EconomicEvent, MacroSnapshot, MarketIntelligenceContext, NewsArticle

    result = _result(rating=Rating.DEVELOPING, missing_conditions=["Retracement"])
    bullish_mi = MarketIntelligenceContext(
        data_available=True, generated_at="2026-01-01T00:00:00+00:00",
        macro=MacroSnapshot(data_available=True, source="real", generated_at="2026-01-01T00:00:00+00:00",
                             fed_funds_rate=5.25, cpi_yoy=3.0, us10y_yield=4.2, freshness="LIVE"),
        events=[EconomicEvent(name="Fed signals dovish pivot", category="Central Bank", importance="HIGH",
                               scheduled_at="2026-01-01T00:00:00+00:00", source="real", country="US")],
        news=[NewsArticle(id="1", headline="Gold surges to record high on Fed dovish pivot", source="wire",
                           published_at="2026-01-01T00:00:00+00:00", retrieved_at="2026-01-01T00:00:00+00:00")],
        sources=["real"],
    )
    evidence = ContextualEvidence(market_intelligence=bullish_mi, market_intelligence_relevant=True)
    monkeypatch.setattr(evaluator_mod, "get_provider",
                         lambda: _RecordingProvider(reply="This looks extremely bullish for gold."))

    enriched = attach_llm_explanation(result, evidence=evidence)

    assert enriched.rating == Rating.DEVELOPING
    assert enriched.contextual_analysis.rating == Rating.DEVELOPING
    assert enriched.contextual_analysis.deterministic_rating == Rating.DEVELOPING
    assert enriched.contextual_analysis.market_intelligence.relevant is True  # evidence WAS surfaced...
    assert "Retracement" in enriched.contextual_analysis.uncertainties  # ...but never resolved the gap


def test_contextual_analysis_rating_is_literally_copied_not_llm_generated():
    """Structural proof, not just behavioral: attach_llm_explanation never
    asks the LLM for a rating field at all (see _build_contextual_analysis),
    so there's no code path capable of setting it independently."""
    import inspect
    source = inspect.getsource(evaluator_mod._build_contextual_analysis)
    assert "interpretation" in source  # the only LLM-sourced field
    # rating/deterministic_rating both assigned from result.rating, never a
    # parsed/parameterized "llm reply" value.
    assert "rating=result.rating" in source
    assert "deterministic_rating=result.rating" in source


# ---------------------------------------------------------------------------
# contextual_analysis populates even when the LLM is unavailable
# ---------------------------------------------------------------------------

def test_contextual_analysis_populates_when_provider_unconfigured(monkeypatch):
    result = _result()

    def _raise_config_error():
        raise ProviderConfigError("AI_API_KEY is not set.")

    monkeypatch.setattr(evaluator_mod, "get_provider", _raise_config_error)
    enriched = attach_llm_explanation(result, evidence=ContextualEvidence())

    assert enriched.contextual_analysis is not None
    assert enriched.contextual_analysis.rating == Rating.A_PLUS
    assert "unavailable" in enriched.contextual_analysis.interpretation.lower()
    assert enriched.contextual_analysis.technical_summary  # deterministic sections still populate


def test_contextual_analysis_populates_when_provider_request_fails(monkeypatch):
    result = _result()
    monkeypatch.setattr(evaluator_mod, "get_provider", lambda: _FailingProvider())

    enriched = attach_llm_explanation(result, evidence=ContextualEvidence())

    assert enriched.contextual_analysis is not None
    assert "unavailable" in enriched.contextual_analysis.interpretation.lower()
    assert enriched.contextual_analysis.risk_context  # deterministic section still populated


def test_contextual_analysis_stays_none_when_no_evidence_given(monkeypatch):
    """Backward compatibility: the pre-Stage-10 call shape."""
    result = _result()
    monkeypatch.setattr(evaluator_mod, "get_provider", lambda: _RecordingProvider())
    enriched = attach_llm_explanation(result)
    assert enriched.contextual_analysis is None
    assert enriched.llm_explanation == "A clear, safe interpretation."


# ---------------------------------------------------------------------------
# Both safety filters apply to the interpretation field too
# ---------------------------------------------------------------------------

def test_interpretation_is_safety_filtered_for_actionable_directives(monkeypatch):
    result = _result()
    monkeypatch.setattr(evaluator_mod, "get_provider",
                         lambda: _RecordingProvider(reply="You should BUY NOW at market."))
    enriched = attach_llm_explanation(result, evidence=ContextualEvidence())
    assert "BUY NOW" not in enriched.contextual_analysis.interpretation
    assert "BUY NOW" not in enriched.llm_explanation


def test_interpretation_is_safety_filtered_for_predictive_probability_claims(monkeypatch):
    result = _result()
    monkeypatch.setattr(evaluator_mod, "get_provider",
                         lambda: _RecordingProvider(reply="This setup has a 90% chance of winning."))
    enriched = attach_llm_explanation(result, evidence=ContextualEvidence())
    assert "90%" not in enriched.contextual_analysis.interpretation
    assert "90%" not in enriched.llm_explanation


# ---------------------------------------------------------------------------
# STRATEGY_SYSTEM_PROMPT states the evidence hierarchy and descriptive-only rule
# ---------------------------------------------------------------------------

def test_system_prompt_states_the_evidence_precedence_order():
    assert "precedence order" in STRATEGY_SYSTEM_PROMPT.lower()
    assert "the deterministic" in STRATEGY_SYSTEM_PROMPT.lower()
    assert "None of it can change the rating above" in STRATEGY_SYSTEM_PROMPT


def test_system_prompt_forbids_probability_claims_for_historical_similarity():
    assert "percentage chance of winning" in STRATEGY_SYSTEM_PROMPT
    assert '"this will win"' in STRATEGY_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Structured output validation
# ---------------------------------------------------------------------------

def test_contextual_analysis_out_has_the_expected_shape(monkeypatch):
    result = _result()
    monkeypatch.setattr(evaluator_mod, "get_provider", lambda: _RecordingProvider())
    enriched = attach_llm_explanation(result, evidence=ContextualEvidence())

    dumped = enriched.contextual_analysis.model_dump()
    assert set(dumped.keys()) == {
        "rating", "deterministic_rating", "technical_summary", "strategy_summary", "market_intelligence",
        "historical_context", "risk_context", "interpretation", "uncertainties",
        "llm_provider", "llm_model", "llm_error",
    }
    assert set(dumped["market_intelligence"].keys()) == {
        "relevant", "macro", "events", "news", "cross_asset", "freshness", "overall",
    }
