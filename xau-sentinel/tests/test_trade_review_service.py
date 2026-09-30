"""Tests for ai/trade_review/service.py — get_review() never calls the
LLM; generate_review() mirrors ai/explanations/service.py's exact call/
safety-filter shape; the LLM path can never mutate strategy_alignment/
outcome/deviations; no automatic memory write."""
import inspect

import pytest

import ai.trade_review.service as service_mod
from ai.trade_review import store
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply="The trade followed the recorded H1 bias and MSS confirmation."):
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
def _init_and_seed(temp_db, monkeypatch):
    from journal import trades as trades_repo
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-01", "trade_time": "10:00", "symbol": "XAUUSD", "direction": "BUY",
         "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0, "planned_rr": 3.0},
        {"h1_bias": "BULLISH", "liquidity": "Previous Day Low swept", "mss": "Bullish", "displacement": "Bullish"},
    )
    trades_repo.close_trade(trade_id, {"exit_price": 3730.0, "result": "WIN", "pnl": 300.0,
                                        "r_multiple": 3.0, "duration_minutes": 45})
    global TRADE_ID
    TRADE_ID = trade_id

    # Evidence sources stay fast/offline — these tests are about the
    # LLM/assembly flow, not each evidence source individually.
    from ai.trade_review import context as ctx
    monkeypatch.setattr(ctx.similarity_engine, "resolve_query_features", lambda trade_id=None: (None, None))
    monkeypatch.setattr(ctx.knowledge_retrieval, "retrieve", lambda q: [])
    monkeypatch.setattr(ctx.memory_retrieval, "retrieve_memory", lambda q: [])


# ---------------------------------------------------------------------------
# get_review() — deterministic only, never calls the LLM
# ---------------------------------------------------------------------------

def test_get_review_returns_deterministic_fields_without_interpretation():
    review = service_mod.get_review(TRADE_ID)
    assert review.trade_id == TRADE_ID
    assert review.interpretation is None


def test_get_review_never_calls_the_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(service_mod, "get_provider", lambda: calls.append(1) or _RecordingProvider())
    service_mod.get_review(TRADE_ID)
    assert calls == []


def test_get_review_raises_not_found_for_unknown_trade():
    with pytest.raises(service_mod.TradeReviewNotFoundError):
        service_mod.get_review(999999)


def test_get_review_module_source_never_mentions_get_provider():
    """Structural: get_review() itself has no code path to a provider —
    only generate_review() does."""
    source = inspect.getsource(service_mod.get_review)
    assert "get_provider" not in source
    assert ".chat(" not in source


# ---------------------------------------------------------------------------
# generate_review() — success / degradation / safety filtering
# ---------------------------------------------------------------------------

def test_generate_review_populates_interpretation(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(service_mod, "get_provider", lambda: provider)
    review = service_mod.generate_review(TRADE_ID)
    assert review.interpretation == provider.reply
    assert review.llm_provider == "fake"


def test_generate_review_raises_not_found_for_unknown_trade():
    with pytest.raises(service_mod.TradeReviewNotFoundError):
        service_mod.generate_review(999999)


def test_generate_review_degrades_when_provider_unconfigured(monkeypatch):
    def raise_config():
        raise ProviderConfigError("AI_API_KEY is not set.")
    monkeypatch.setattr(service_mod, "get_provider", raise_config)
    review = service_mod.generate_review(TRADE_ID)
    assert "unavailable" in review.interpretation.lower()
    assert review.strategy_alignment is not None  # deterministic fields still populated


def test_generate_review_degrades_when_provider_request_fails(monkeypatch):
    monkeypatch.setattr(service_mod, "get_provider", lambda: _FailingProvider())
    review = service_mod.generate_review(TRADE_ID)
    assert "unavailable" in review.interpretation.lower()


@pytest.mark.parametrize("reply", [
    "You should buy this setup.",
    "I recommend entering this trade.",
    "This setup has a 90% chance of winning.",
])
def test_unsafe_llm_reply_is_replaced_by_safety_override(monkeypatch, reply):
    from ai.prompts import SAFETY_OVERRIDE_MESSAGE
    monkeypatch.setattr(service_mod, "get_provider", lambda: _RecordingProvider(reply=reply))
    review = service_mod.generate_review(TRADE_ID)
    assert review.interpretation == SAFETY_OVERRIDE_MESSAGE


def test_get_review_after_generate_serves_the_cached_interpretation(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(service_mod, "get_provider", lambda: provider)
    service_mod.generate_review(TRADE_ID)

    review = service_mod.get_review(TRADE_ID)
    assert review.interpretation == provider.reply


# ---------------------------------------------------------------------------
# Structural guarantees: LLM path never mutates deterministic fields, no
# automatic memory write.
# ---------------------------------------------------------------------------

def test_deterministic_fields_unchanged_regardless_of_llm_reply(monkeypatch):
    monkeypatch.setattr(service_mod, "get_provider",
                         lambda: _RecordingProvider(reply="This trade was clearly a mistake and poorly planned."))
    before = service_mod.get_review(TRADE_ID)
    generated = service_mod.generate_review(TRADE_ID)
    assert generated.strategy_alignment == before.strategy_alignment
    assert generated.outcome == before.outcome
    assert generated.deviations == before.deviations


def test_service_never_creates_a_memory_record():
    source = inspect.getsource(service_mod)
    for banned in ("create_memory", "memory.store"):
        assert banned not in source
