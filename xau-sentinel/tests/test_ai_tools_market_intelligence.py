"""Tests for ai/tools/market_intelligence_tools.py — all five wrappers are
read-only and degrade to data_available=False on a provider failure,
never crashing or fabricating a value."""
import config
from ai.tools import market_intelligence_tools as mi_tools


def test_get_macro_context_returns_macro_and_gold_fundamentals():
    result = mi_tools.get_macro_context({})
    assert result.data_available is True
    assert "macro" in result.data
    assert "gold_fundamentals" in result.data
    assert result.data["macro"]["fed_funds_rate"] is not None


def test_get_macro_context_degrades_on_provider_error(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_MACRO_PROVIDER", "not-a-real-provider")
    result = mi_tools.get_macro_context({})
    assert result.data_available is False
    assert result.reason


def test_get_cross_asset_context_returns_all_fields():
    result = mi_tools.get_cross_asset_context({})
    assert result.data_available is True
    assert result.data["dxy"] is not None
    assert result.data["vix"] is not None


def test_get_cross_asset_context_degrades_on_provider_error(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_CROSS_ASSET_PROVIDER", "not-a-real-provider")
    result = mi_tools.get_cross_asset_context({})
    assert result.data_available is False


def test_get_economic_events_returns_a_list():
    result = mi_tools.get_economic_events({})
    assert result.data_available is True
    assert result.data["count"] > 0
    assert len(result.data["events"]) == result.data["count"]


def test_get_economic_events_respects_days_arguments():
    result = mi_tools.get_economic_events({"days_ahead": 1, "days_back": 0})
    assert result.data_available is True  # still succeeds, just a narrower window


def test_get_economic_events_degrades_on_provider_error(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_EVENTS_PROVIDER", "not-a-real-provider")
    result = mi_tools.get_economic_events({})
    assert result.data_available is False


def test_get_market_news_returns_deduplicated_articles():
    result = mi_tools.get_market_news({})
    assert result.data_available is True
    assert result.data["count"] > 0
    headlines = [a["headline"] for a in result.data["articles"]]
    assert len(headlines) == len(set(headlines))  # no duplicates


def test_get_market_news_respects_limit():
    result = mi_tools.get_market_news({"limit": 1})
    assert result.data["count"] <= 1


def test_get_market_news_degrades_on_provider_error(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_NEWS_PROVIDER", "not-a-real-provider")
    result = mi_tools.get_market_news({})
    assert result.data_available is False


def test_get_market_intelligence_returns_the_full_aggregate():
    result = mi_tools.get_market_intelligence({})
    assert result.data_available is True
    assert result.data["macro"] is not None
    assert result.data["gold_fundamentals"] is not None
    assert result.data["cross_asset"] is not None
    assert len(result.data["events"]) > 0
    assert len(result.data["news"]) > 0
    assert "sources" in result.data
