"""News provider factory. Stage 11 adds "real" (two RSS feeds, see
providers/real.py) alongside "mock"; default tied to config.MODE, still
overridable via MARKET_INTEL_NEWS_PROVIDER.

The normalization/dedup helpers used to live in this file directly; they
now live in providers/dedup.py (Stage 11) so both this factory and
providers/real.py can depend on them without a circular import (real.py
needs stable_id() to assign each fetched article's id; this file needs
real.py for its factory registration). Re-exported here unchanged so every
existing `from ai.market_intelligence.providers.news import stable_id,
dedupe_articles` caller — ai/market_intelligence/context.py,
ai/tools/market_intelligence_tools.py, and the Stage 9 test suite — needs
no changes.
"""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseNewsProvider
from ai.market_intelligence.providers.dedup import dedupe_articles, stable_id  # noqa: F401  (re-exported)
from ai.market_intelligence.providers.mock import MockNewsProvider
from ai.market_intelligence.providers.real import RealNewsProvider

_PROVIDERS = {"mock": MockNewsProvider, "real": RealNewsProvider}


def get_news_provider(name: Optional[str] = None) -> BaseNewsProvider:
    provider_name = (name or config.MARKET_INTEL_NEWS_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_NEWS_PROVIDER '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
