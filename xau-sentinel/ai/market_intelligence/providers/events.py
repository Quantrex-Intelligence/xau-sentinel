"""Economic events provider factory — the seam a real calendar plugs into.
Stage 11 adds "real" (FRED observations + release-dates, see
providers/real.py) alongside "mock"; default tied to config.MODE, still
overridable via MARKET_INTEL_EVENTS_PROVIDER."""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseEventsProvider
from ai.market_intelligence.providers.mock import MockEventsProvider
from ai.market_intelligence.providers.real import RealEventsProvider

_PROVIDERS = {"mock": MockEventsProvider, "real": RealEventsProvider}


def get_events_provider(name: Optional[str] = None) -> BaseEventsProvider:
    provider_name = (name or config.MARKET_INTEL_EVENTS_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_EVENTS_PROVIDER '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
