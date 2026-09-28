"""Assembles the full MarketIntelligenceContext from all four provider
categories. Each provider call is independently wrapped so one broken/
misconfigured provider degrades only its own section, never the whole
context (same per-section independence philosophy as ai/context.py's
AssembledContext). Applies news staleness filtering and deduplication
uniformly, regardless of which news provider is configured.

Never duplicates Sentinel's own technical output — nothing here calls
analysis/, api.snapshot, or mt5.market_data. This is a separate evidence
source, not a second copy of the deterministic engine (see Stage 9 spec's
"do not duplicate Sentinel's technical engine output").
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import config
from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot,
    MarketIntelligenceContext, NewsArticle,
)
from ai.market_intelligence.providers.cross_asset import get_cross_asset_provider
from ai.market_intelligence.providers.events import get_events_provider
from ai.market_intelligence.providers.macro import get_macro_provider
from ai.market_intelligence.providers.news import dedupe_articles, get_news_provider


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _get_macro() -> Optional[MacroSnapshot]:
    try:
        return get_macro_provider().get_macro_snapshot()
    except Exception:  # noqa: BLE001 - one broken provider must never take down the whole context
        return None


def _get_gold_fundamentals() -> Optional[GoldFundamentals]:
    try:
        return get_macro_provider().get_gold_fundamentals()
    except Exception:  # noqa: BLE001
        return None


def _get_cross_asset() -> Optional[CrossAssetSnapshot]:
    try:
        return get_cross_asset_provider().get_cross_asset_snapshot()
    except Exception:  # noqa: BLE001
        return None


def _get_events(days_ahead: int, days_back: int) -> List[EconomicEvent]:
    try:
        return get_events_provider().get_economic_events(days_ahead=days_ahead, days_back=days_back)
    except Exception:  # noqa: BLE001
        return []


def _get_news(limit: int, max_age_hours: float) -> List[NewsArticle]:
    try:
        articles = get_news_provider().get_recent_news(limit=limit, max_age_hours=max_age_hours)
    except Exception:  # noqa: BLE001
        return []

    cutoff = _now() - timedelta(hours=max_age_hours)
    fresh = [a for a in articles if _parse_iso(a.published_at) is None or _parse_iso(a.published_at) >= cutoff]
    return dedupe_articles(fresh)[:limit]


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def build_market_intelligence_context(
    include_macro: bool = True, include_gold_fundamentals: bool = True,
    include_cross_asset: bool = True, include_events: bool = True, include_news: bool = True,
    news_limit: Optional[int] = None, news_max_age_hours: Optional[float] = None,
    events_days_ahead: Optional[int] = None, events_days_back: Optional[int] = None,
) -> MarketIntelligenceContext:
    macro = _get_macro() if include_macro else None
    gold_fundamentals = _get_gold_fundamentals() if include_gold_fundamentals else None
    cross_asset = _get_cross_asset() if include_cross_asset else None
    events = _get_events(
        events_days_ahead if events_days_ahead is not None else config.MARKET_INTEL_EVENTS_DAYS_AHEAD,
        events_days_back if events_days_back is not None else config.MARKET_INTEL_EVENTS_DAYS_BACK,
    ) if include_events else []
    news = _get_news(
        news_limit if news_limit is not None else config.MARKET_INTEL_NEWS_DEFAULT_LIMIT,
        news_max_age_hours if news_max_age_hours is not None else config.MARKET_INTEL_NEWS_MAX_AGE_HOURS,
    ) if include_news else []

    sources = sorted({
        s.source for s in (macro, gold_fundamentals, cross_asset)
        if s is not None and s.data_available
    } | {e.source for e in events} | {n.source for n in news})

    data_available = bool(
        (macro and macro.data_available) or (gold_fundamentals and gold_fundamentals.data_available)
        or (cross_asset and cross_asset.data_available) or events or news
    )

    return MarketIntelligenceContext(
        data_available=data_available, generated_at=_now_iso(),
        macro=macro, gold_fundamentals=gold_fundamentals, cross_asset=cross_asset,
        events=events, news=news, sources=sources,
    )
