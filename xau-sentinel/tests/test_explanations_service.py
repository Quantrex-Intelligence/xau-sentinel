"""Tests for ai/explanations/service.py — the LLM call/safety-filter/
assembly flow, degradation when the provider is unavailable, and the
structural guarantee that explanation generation can never change an A+
rating, a deterministic fact, or a risk status."""
import inspect

import pytest

import ai.explanations.service as service_mod
from ai.explanations import store
from ai.monitoring import store as monitoring_store
from ai.monitoring.models import AlertEvent, AlertType, Severity
from ai.providers.base import (
    BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse,
)


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply="The setup formed after a liquidity sweep and MSS confirmation."):
        self.reply = reply
        self.calls = []

    def chat(self, system, messages, tools=None):
        self.calls.append((system, messages))
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


class _FailingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def chat(self, system, messages, tools=None):
        raise ProviderRequestError("simulated network failure")


@pytest.fixture(autouse=True)
def _init_tables(temp_db):
    return temp_db


@pytest.fixture(autouse=True)
def _stub_evidence(monkeypatch):
    """Keep evidence gathering fast/offline — these tests are about the
    LLM/assembly flow, not about each evidence source (see
    test_explanations_context.py for that)."""
    from ai.explanations import context as ctx
    monkeypatch.setattr(ctx.mi_context, "build_market_intelligence_context", lambda: None)
    monkeypatch.setattr(ctx.similarity_engine, "resolve_query_features", lambda trade_id=None: (None, None))
    monkeypatch.setattr(ctx.knowledge_retrieval, "retrieve", lambda q: [])
    monkeypatch.setattr(ctx.memory_retrieval, "retrieve_memory", lambda q: [])


def _seed_alert(**overrides):
    defaults = dict(
        type=AlertType.APLUS_SETUP_DETECTED, severity=Severity.INFO, title="A+ setup detected — BUY",
        message="BUY A+ setup confirmed.", dedup_key="k1",
        payload={"direction": "BUY", "entry": 3700.0, "stop_loss": 3690.0, "target": 3730.0, "rr": 3.0, "rating": "A+"},
    )
    defaults.update(overrides)
    return monitoring_store.create_alert(AlertEvent(**defaults))


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

def test_explain_alert_populates_interpretation_and_deterministic_facts(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(service_mod, "get_provider", lambda: provider)
    alert = _seed_alert()

    explanation = service_mod.explain_alert(alert.id)

    assert explanation.subject_type == "alert"
    assert explanation.subject_id == alert.id
    assert explanation.interpretation == provider.reply
    assert explanation.llm_provider == "fake"
    assert any("BUY" in f for f in explanation.deterministic_facts)


def test_explain_alert_raises_not_found_for_unknown_id():
    with pytest.raises(service_mod.ExplanationNotFoundError):
        service_mod.explain_alert(99999)


# ---------------------------------------------------------------------------
# Degradation — provider unavailable never breaks the rest of the explanation
# ---------------------------------------------------------------------------

def test_explain_alert_degrades_when_provider_unconfigured(monkeypatch):
    def raise_config():
        raise ProviderConfigError("AI_API_KEY is not set.")
    monkeypatch.setattr(service_mod, "get_provider", raise_config)
    alert = _seed_alert()

    explanation = service_mod.explain_alert(alert.id)

    assert explanation.llm_error is not None
    assert "unavailable" in explanation.interpretation.lower()
    assert explanation.deterministic_facts  # still populated


def test_explain_alert_degrades_when_provider_request_fails(monkeypatch):
    monkeypatch.setattr(service_mod, "get_provider", lambda: _FailingProvider())
    alert = _seed_alert()

    explanation = service_mod.explain_alert(alert.id)

    assert "unavailable" in explanation.interpretation.lower()
    assert explanation.deterministic_facts


# ---------------------------------------------------------------------------
# Safety filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "You should BUY NOW at market.",
    "SELL NOW before it drops.",
    "This setup has a 90% chance of winning.",
    "Based on similar trades, this trade will win.",
])
def test_unsafe_llm_reply_is_replaced_by_safety_override(monkeypatch, reply):
    from ai.prompts import SAFETY_OVERRIDE_MESSAGE
    monkeypatch.setattr(service_mod, "get_provider", lambda: _RecordingProvider(reply=reply))
    alert = _seed_alert()

    explanation = service_mod.explain_alert(alert.id)

    assert explanation.interpretation == SAFETY_OVERRIDE_MESSAGE


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_explain_alert_serves_cached_result_without_calling_the_llm_again(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(service_mod, "get_provider", lambda: provider)
    alert = _seed_alert()

    service_mod.explain_alert(alert.id)
    service_mod.explain_alert(alert.id)

    assert len(provider.calls) == 1


def test_explain_alert_force_regenerates(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(service_mod, "get_provider", lambda: provider)
    alert = _seed_alert()

    service_mod.explain_alert(alert.id)
    service_mod.explain_alert(alert.id, force=True)

    assert len(provider.calls) == 2


# ---------------------------------------------------------------------------
# Trade explanations
# ---------------------------------------------------------------------------

def test_explain_trade_raises_not_found_for_unknown_id():
    with pytest.raises(service_mod.ExplanationNotFoundError):
        service_mod.explain_trade(99999)


def test_explain_trade_populates_facts_from_the_trade_record(monkeypatch):
    from journal import trades as trades_repo
    monkeypatch.setattr(service_mod, "get_provider", lambda: _RecordingProvider())
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-01", "trade_time": "10:00", "symbol": "XAUUSD", "direction": "BUY",
         "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0},
        {"h1_bias": "BULLISH"},
    )

    explanation = service_mod.explain_trade(trade_id)

    assert explanation.subject_type == "trade"
    assert explanation.explanation_type == "TRADE"
    assert any("BUY" in f for f in explanation.deterministic_facts)
    assert explanation.supporting_context == []  # Market Intelligence never gathered for a trade


# ---------------------------------------------------------------------------
# A+ authority / structural guarantees
# ---------------------------------------------------------------------------

def test_explanation_never_mutates_the_underlying_alert(monkeypatch):
    monkeypatch.setattr(service_mod, "get_provider",
                         lambda: _RecordingProvider(reply="This setup looks like it should be rated differently."))
    alert = _seed_alert()
    before = monitoring_store.get_by_id(alert.id)

    service_mod.explain_alert(alert.id)

    after = monitoring_store.get_by_id(alert.id)
    assert after.payload == before.payload
    assert after.payload["rating"] == "A+"


def test_service_never_calls_evaluate_deterministic_or_writes_trades():
    source = inspect.getsource(service_mod)
    for banned in ("evaluate_deterministic", "evaluate_current_setup", "create_trade", "close_trade",
                   "INSERT INTO trades", "UPDATE trades"):
        assert banned not in source


def test_system_prompt_states_the_authority_hierarchy_and_no_directive_rule():
    from ai.explanations.prompts import EXPLANATION_SYSTEM_PROMPT
    assert "authoritative" in EXPLANATION_SYSTEM_PROMPT
    assert "Never issue a trading instruction" in EXPLANATION_SYSTEM_PROMPT
    assert "Never invent a value" in EXPLANATION_SYSTEM_PROMPT
    assert "confidence score" in EXPLANATION_SYSTEM_PROMPT
