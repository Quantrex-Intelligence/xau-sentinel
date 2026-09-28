"""Cross-asset provider factory — the seam a real quote feed (DXY/yields/
VIX/equity index/silver) plugs into. Stage 11 adds "real" (Yahoo Finance +
FRED, see providers/real.py) alongside "mock"; default tied to config.MODE,
still overridable via MARKET_INTEL_CROSS_ASSET_PROVIDER."""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseCrossAssetProvider
from ai.market_intelligence.providers.mock import MockCrossAssetProvider
from ai.market_intelligence.providers.real import RealCrossAssetProvider

_PROVIDERS = {"mock": MockCrossAssetProvider, "real": RealCrossAssetProvider}


def get_cross_asset_provider(name: Optional[str] = None) -> BaseCrossAssetProvider:
    provider_name = (name or config.MARKET_INTEL_CROSS_ASSET_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_CROSS_ASSET_PROVIDER '{provider_name}'. "
            f"Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
