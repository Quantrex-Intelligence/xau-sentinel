"""Macro provider factory — the seam a real macro-data backend (a free
government/central-bank API, e.g. FRED) plugs into later with no change to
ai/market_intelligence/context.py or the tools. Only "mock" exists today."""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseMacroProvider
from ai.market_intelligence.providers.mock import MockMacroProvider

_PROVIDERS = {"mock": MockMacroProvider}


def get_macro_provider(name: Optional[str] = None) -> BaseMacroProvider:
    provider_name = (name or config.MARKET_INTEL_MACRO_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_MACRO_PROVIDER '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
