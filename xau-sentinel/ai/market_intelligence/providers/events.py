"""Economic events provider factory — the seam a real calendar (a free
public source, e.g. an official statistics agency feed) plugs into later.
Only "mock" exists today."""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseEventsProvider
from ai.market_intelligence.providers.mock import MockEventsProvider

_PROVIDERS = {"mock": MockEventsProvider}


def get_events_provider(name: Optional[str] = None) -> BaseEventsProvider:
    provider_name = (name or config.MARKET_INTEL_EVENTS_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_EVENTS_PROVIDER '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
