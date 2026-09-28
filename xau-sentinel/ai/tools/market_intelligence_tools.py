"""Read-only tool wrappers over ai.market_intelligence — external, time-
stamped evidence (macro/gold fundamentals/cross-asset/events/news), never
auto-injected into every turn (see ai/assistant.py, unmodified for Stage 9)
and never authoritative over the deterministic engine, the A+ evaluation,
or FundedNext risk facts (ai/prompts.py ground rule 10)."""
from dataclasses import asdict

import config
from ai.market_intelligence import context as mi_context
from ai.market_intelligence.providers.cross_asset import get_cross_asset_provider
from ai.market_intelligence.providers.events import get_events_provider
from ai.market_intelligence.providers.macro import get_macro_provider
from ai.market_intelligence.providers.news import get_news_provider
from ai.market_intelligence.quality import assess_news_quality, build_intelligence_summary
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult

_EMPTY_SCHEMA = {"type": "object", "properties": {}}


def get_macro_context(_args: dict) -> ToolResult:
    try:
        provider = get_macro_provider()
        macro = provider.get_macro_snapshot()
        gold = provider.get_gold_fundamentals()
    except Exception as exc:  # noqa: BLE001 - a provider failure degrades, never crashes the turn
        return ToolResult(data_available=False, reason=str(exc), source="ai.market_intelligence")
    if not macro.data_available:
        return ToolResult(data_available=False, reason=macro.reason or "Macro data unavailable.",
                           source="ai.market_intelligence")
    return ToolResult(
        data_available=True, timestamp=macro.generated_at, source=f"ai.market_intelligence:{macro.source}",
        data={"macro": asdict(macro), "gold_fundamentals": asdict(gold)},
    )


def get_cross_asset_context(_args: dict) -> ToolResult:
    try:
        snapshot = get_cross_asset_provider().get_cross_asset_snapshot()
    except Exception as exc:  # noqa: BLE001
        return ToolResult(data_available=False, reason=str(exc), source="ai.market_intelligence")
    if not snapshot.data_available:
        return ToolResult(data_available=False, reason=snapshot.reason or "Cross-asset data unavailable.",
                           source="ai.market_intelligence")
    return ToolResult(
        data_available=True, timestamp=snapshot.generated_at,
        source=f"ai.market_intelligence:{snapshot.source}", data=asdict(snapshot),
    )


def get_economic_events(args: dict) -> ToolResult:
    days_ahead = args.get("days_ahead", config.MARKET_INTEL_EVENTS_DAYS_AHEAD)
    days_back = args.get("days_back", config.MARKET_INTEL_EVENTS_DAYS_BACK)
    try:
        events = get_events_provider().get_economic_events(days_ahead=days_ahead, days_back=days_back)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(data_available=False, reason=str(exc), source="ai.market_intelligence")
    return ToolResult(
        data_available=True, source="ai.market_intelligence",
        data={"events": [asdict(e) for e in events], "count": len(events)},
    )


def get_market_news(args: dict) -> ToolResult:
    """Stage 12: filters through the same
    ai.market_intelligence.quality.assess_news_quality() as
    ai/market_intelligence/context.py::_get_news() — previously this tool
    deduped but never applied the staleness cutoff, so a stale article
    could reach the LLM tool loop unfiltered even though the aggregate
    /api/market-intelligence path already excluded it."""
    limit = args.get("limit", config.MARKET_INTEL_NEWS_DEFAULT_LIMIT)
    max_age_hours = args.get("max_age_hours", config.MARKET_INTEL_NEWS_MAX_AGE_HOURS)
    try:
        raw = get_news_provider().get_recent_news(limit=limit, max_age_hours=max_age_hours)
        articles = [q.article for q in assess_news_quality(raw, max_age_hours=max_age_hours)][:limit]
    except Exception as exc:  # noqa: BLE001
        return ToolResult(data_available=False, reason=str(exc), source="ai.market_intelligence")
    return ToolResult(
        data_available=True, source="ai.market_intelligence",
        data={"articles": [asdict(a) for a in articles], "count": len(articles)},
    )


def get_market_intelligence(_args: dict) -> ToolResult:
    ctx = mi_context.build_market_intelligence_context()
    summary = build_intelligence_summary(ctx)
    return ToolResult(
        data_available=ctx.data_available, timestamp=ctx.generated_at, source="ai.market_intelligence",
        data={
            "macro": asdict(ctx.macro) if ctx.macro else None,
            "gold_fundamentals": asdict(ctx.gold_fundamentals) if ctx.gold_fundamentals else None,
            "cross_asset": asdict(ctx.cross_asset) if ctx.cross_asset else None,
            "events": [asdict(e) for e in ctx.events],
            "news": [asdict(n) for n in ctx.news],
            "sources": ctx.sources,
            "quality_summary": asdict(summary),
        },
    )


register(ToolSpec(
    "get_macro_context", "Macro Context",
    "Current broad macroeconomic snapshot (Fed funds rate, CPI, unemployment, GDP growth, Treasury "
    "yields) and gold-specific fundamentals (USD bias, real yields, central-bank demand, ETF flow trend). "
    "External data, time-stamped — never authoritative over the deterministic setup engine.",
    _EMPTY_SCHEMA, get_macro_context,
))
register(ToolSpec(
    "get_cross_asset_context", "Cross-Asset Context",
    "Current DXY, US 2Y/10Y yields, real yield, VIX, a major equity index, and silver price — external "
    "data, time-stamped, for context only.",
    _EMPTY_SCHEMA, get_cross_asset_context,
))
register(ToolSpec(
    "get_economic_events", "Economic Events",
    "Upcoming and recent economic calendar events with actual/forecast/previous values and importance, "
    "when available.",
    {"type": "object", "properties": {
        "days_ahead": {"type": "integer"}, "days_back": {"type": "integer"},
    }},
    get_economic_events,
))
register(ToolSpec(
    "get_market_news", "Market News",
    "Recent, deduplicated news headlines relevant to gold/macro markets, each with a source, timestamp, "
    "and summary — descriptive reporting, never a forecast.",
    {"type": "object", "properties": {
        "limit": {"type": "integer"}, "max_age_hours": {"type": "number"},
    }},
    get_market_news,
))
register(ToolSpec(
    "get_market_intelligence", "Full Market Intelligence",
    "The full Market Intelligence snapshot in one call: macro, gold fundamentals, cross-asset, upcoming "
    "economic events, and recent news together.",
    _EMPTY_SCHEMA, get_market_intelligence,
))
