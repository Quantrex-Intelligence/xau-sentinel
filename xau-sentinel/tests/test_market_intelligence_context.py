"""Tests for ai/market_intelligence/context.py's full aggregate assembly:
structured shape, generated_at/sources population, per-section provider
independence (one broken provider never takes down the whole context), and
the "never duplicates Sentinel's technical output" guarantee."""
import inspect

from ai.market_intelligence import context as context_mod
from ai.market_intelligence.context import build_market_intelligence_context


def test_context_is_fully_populated_with_all_mock_providers():
    ctx = build_market_intelligence_context()
    assert ctx.data_available is True
    assert ctx.generated_at is not None
    assert ctx.macro is not None and ctx.macro.data_available
    assert ctx.gold_fundamentals is not None and ctx.gold_fundamentals.data_available
    assert ctx.cross_asset is not None and ctx.cross_asset.data_available
    assert len(ctx.events) > 0
    assert len(ctx.news) > 0
    assert "mock" in ctx.sources


def test_context_include_flags_skip_the_corresponding_section():
    ctx = build_market_intelligence_context(
        include_macro=False, include_gold_fundamentals=False,
        include_cross_asset=False, include_events=False, include_news=False,
    )
    assert ctx.macro is None
    assert ctx.gold_fundamentals is None
    assert ctx.cross_asset is None
    assert ctx.events == []
    assert ctx.news == []
    assert ctx.data_available is False


def test_one_broken_provider_does_not_take_down_the_whole_context(monkeypatch):
    def _boom():
        raise RuntimeError("simulated macro provider failure")

    monkeypatch.setattr(context_mod, "get_macro_provider", _boom)

    ctx = build_market_intelligence_context()
    assert ctx.macro is None  # degraded, not raised
    assert ctx.gold_fundamentals is None  # also depends on the macro provider
    # Everything else still populated.
    assert ctx.cross_asset is not None and ctx.cross_asset.data_available
    assert len(ctx.events) > 0
    assert len(ctx.news) > 0


def test_context_data_available_false_when_every_provider_fails(monkeypatch):
    def _boom(*_a, **_kw):
        raise RuntimeError("simulated total outage")

    monkeypatch.setattr(context_mod, "get_macro_provider", _boom)
    monkeypatch.setattr(context_mod, "get_cross_asset_provider", _boom)
    monkeypatch.setattr(context_mod, "get_events_provider", _boom)
    monkeypatch.setattr(context_mod, "get_news_provider", _boom)

    ctx = build_market_intelligence_context()
    assert ctx.data_available is False
    assert ctx.macro is None
    assert ctx.events == []
    assert ctx.news == []


def test_context_never_imports_sentinels_technical_engine():
    """Stage 9 spec: 'do not duplicate Sentinel's technical engine output' —
    proven structurally: this module never touches analysis/, api.snapshot,
    or mt5.market_data. Checked against the actual import statements, not
    the module's own prose (its docstring explains this same guarantee and
    names those modules explicitly, which would otherwise false-positive a
    plain substring search)."""
    import_lines = [
        ln.strip() for ln in inspect.getsource(context_mod).splitlines()
        if ln.strip().startswith(("import ", "from "))
    ]
    banned = ("analysis", "api.snapshot", "mt5.market_data")
    for line in import_lines:
        for b in banned:
            assert b not in line, f"unexpected import of {b!r}: {line!r}"
    assert not hasattr(context_mod, "detect_setup")
    assert not hasattr(context_mod, "build_snapshot")


def test_sources_are_deduplicated_and_sorted():
    ctx = build_market_intelligence_context()
    assert ctx.sources == sorted(set(ctx.sources))


def test_context_consumes_real_provider_shaped_data_unchanged(monkeypatch):
    """Stage 11: build_market_intelligence_context() must need zero changes
    to consume real-provider output. Proven by faking each factory to
    return objects shaped exactly like Stage 11's real providers (source=
    "real", a populated freshness field) and confirming the aggregate
    context assembles them the same way it does mock data."""
    from datetime import datetime, timedelta, timezone

    from ai.market_intelligence.models import (
        CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot, NewsArticle,
    )

    now = datetime.now(timezone.utc)

    class _FakeRealMacroProvider:
        def get_macro_snapshot(self):
            return MacroSnapshot(
                data_available=True, source="real", generated_at=now.isoformat(),
                fed_funds_rate=5.25, cpi_yoy=3.1, freshness="LIVE",
            )

        def get_gold_fundamentals(self):
            return GoldFundamentals(
                data_available=True, source="real", generated_at=now.isoformat(),
                usd_strength_bias="STRONG", real_yield_10y=1.1, freshness="LIVE",
            )

    class _FakeRealCrossAssetProvider:
        def get_cross_asset_snapshot(self):
            return CrossAssetSnapshot(
                data_available=True, source="real", generated_at=now.isoformat(),
                dxy=101.28, vix=16.13, freshness="LIVE",
            )

    class _FakeRealEventsProvider:
        def get_economic_events(self, days_ahead, days_back):
            return [EconomicEvent(
                name="US CPI (YoY)", category="Inflation", importance="HIGH",
                scheduled_at=now.isoformat(), source="real", actual="3.10%", previous="3.00%",
            )]

    class _FakeRealNewsProvider:
        def get_recent_news(self, limit, max_age_hours):
            article = NewsArticle(
                id="", headline="Federal Reserve issues FOMC statement", source="federal_reserve",
                published_at=now.isoformat(), retrieved_at=now.isoformat(),
                url="https://federalreserve.gov/a", category="macro", importance="HIGH",
            )
            article.id = "fake-stable-id"
            return [article]

    monkeypatch.setattr(context_mod, "get_macro_provider", lambda: _FakeRealMacroProvider())
    monkeypatch.setattr(context_mod, "get_cross_asset_provider", lambda: _FakeRealCrossAssetProvider())
    monkeypatch.setattr(context_mod, "get_events_provider", lambda: _FakeRealEventsProvider())
    monkeypatch.setattr(context_mod, "get_news_provider", lambda: _FakeRealNewsProvider())

    ctx = build_market_intelligence_context()

    assert ctx.data_available is True
    assert ctx.sources == ["federal_reserve", "real"]
    assert ctx.macro.source == "real" and ctx.macro.freshness == "LIVE"
    assert ctx.gold_fundamentals.source == "real" and ctx.gold_fundamentals.freshness == "LIVE"
    assert ctx.cross_asset.source == "real" and ctx.cross_asset.freshness == "LIVE"
    assert len(ctx.events) == 1 and ctx.events[0].source == "real"
    assert len(ctx.news) == 1 and ctx.news[0].source == "federal_reserve"
