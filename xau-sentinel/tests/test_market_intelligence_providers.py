"""Tests for the Market Intelligence mock providers and their factories:
determinism per day, source="mock" metadata, timestamp presence, and the
factory's config error for an unrecognized provider name (the same
unavailable-on-misconfiguration path every other provider family in this
project already has)."""
import pytest

import config
from ai.market_intelligence.providers.cross_asset import get_cross_asset_provider
from ai.market_intelligence.providers.events import get_events_provider
from ai.market_intelligence.providers.macro import get_macro_provider
from ai.market_intelligence.providers.mock import (
    MockCrossAssetProvider, MockEventsProvider, MockMacroProvider, MockNewsProvider,
)
from ai.market_intelligence.providers.news import get_news_provider


def test_macro_provider_returns_available_data_with_timestamp_and_source():
    snapshot = MockMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is True
    assert snapshot.source == "mock"
    assert snapshot.generated_at is not None
    assert snapshot.fed_funds_rate is not None
    assert snapshot.cpi_yoy is not None


def test_macro_provider_is_deterministic_within_the_same_day():
    a = MockMacroProvider().get_macro_snapshot()
    b = MockMacroProvider().get_macro_snapshot()
    assert a.fed_funds_rate == b.fed_funds_rate
    assert a.cpi_yoy == b.cpi_yoy
    assert a.us10y_yield == b.us10y_yield


def test_gold_fundamentals_real_yield_is_derived_from_the_macro_snapshot():
    provider = MockMacroProvider()
    macro = provider.get_macro_snapshot()
    gold = provider.get_gold_fundamentals()
    assert gold.data_available is True
    assert gold.source == "mock"
    assert gold.real_yield_10y == round(macro.us10y_yield - macro.cpi_yoy, 2)
    assert gold.usd_strength_bias in ("STRONG", "NEUTRAL", "WEAK")
    assert gold.central_bank_demand_trend in ("ACCUMULATING", "NEUTRAL", "DISTRIBUTING")
    assert gold.etf_flows_trend in ("INFLOWS", "NEUTRAL", "OUTFLOWS")


def test_cross_asset_provider_returns_all_fields_deterministically():
    a = MockCrossAssetProvider().get_cross_asset_snapshot()
    b = MockCrossAssetProvider().get_cross_asset_snapshot()
    assert a.data_available is True
    assert a.source == "mock"
    assert a.dxy == b.dxy
    assert a.vix == b.vix
    assert a.silver_price == b.silver_price


def test_events_provider_returns_named_events_with_importance_and_schedule():
    events = MockEventsProvider().get_economic_events()
    assert len(events) > 0
    for e in events:
        assert e.name.startswith("[MOCK]")
        assert e.importance in ("HIGH", "MEDIUM", "LOW")
        assert e.scheduled_at is not None
        assert e.source == "mock"


def test_events_provider_is_sorted_by_schedule():
    events = MockEventsProvider().get_economic_events()
    scheduled = [e.scheduled_at for e in events]
    assert scheduled == sorted(scheduled)


def test_news_provider_returns_articles_with_all_required_fields():
    articles = MockNewsProvider().get_recent_news()
    assert len(articles) > 0
    for a in articles:
        assert a.id
        assert a.headline.startswith("[MOCK]")
        assert a.source
        assert a.published_at
        assert a.retrieved_at


def test_news_provider_respects_limit():
    articles = MockNewsProvider().get_recent_news(limit=2)
    assert len(articles) <= 2


# ---------------------------------------------------------------------------
# Factories: default to mock, raise a clear error for an unknown provider
# ---------------------------------------------------------------------------

def test_macro_factory_defaults_to_mock():
    assert isinstance(get_macro_provider(), MockMacroProvider)


def test_macro_factory_raises_for_unknown_provider_name(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_MACRO_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="Unknown MARKET_INTEL_MACRO_PROVIDER"):
        get_macro_provider()


def test_cross_asset_factory_raises_for_unknown_provider_name(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_CROSS_ASSET_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="Unknown MARKET_INTEL_CROSS_ASSET_PROVIDER"):
        get_cross_asset_provider()


def test_events_factory_raises_for_unknown_provider_name(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_EVENTS_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="Unknown MARKET_INTEL_EVENTS_PROVIDER"):
        get_events_provider()


def test_news_factory_raises_for_unknown_provider_name(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_NEWS_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="Unknown MARKET_INTEL_NEWS_PROVIDER"):
        get_news_provider()
