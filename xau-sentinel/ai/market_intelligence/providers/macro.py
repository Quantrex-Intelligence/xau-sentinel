"""Macro provider factory — the seam a real macro-data backend plugs into
with no change to ai/market_intelligence/context.py or the tools. Stage 11
adds "real" (FRED-backed, see providers/real.py) alongside "mock"; the
default is tied to config.MODE (the same mock/live convention
mt5/account.py already uses everywhere else), still overridable via
MARKET_INTEL_MACRO_PROVIDER."""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseMacroProvider
from ai.market_intelligence.providers.mock import MockMacroProvider
from ai.market_intelligence.providers.real import RealMacroProvider

_PROVIDERS = {"mock": MockMacroProvider, "real": RealMacroProvider}


def get_macro_provider(name: Optional[str] = None) -> BaseMacroProvider:
    provider_name = (name or config.MARKET_INTEL_MACRO_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_MACRO_PROVIDER '{provider_name}'. Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
