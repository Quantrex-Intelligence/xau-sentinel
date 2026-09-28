"""Cross-asset provider factory — the seam a real quote feed (DXY/yields/
VIX/equity index/silver) plugs into later. Only "mock" exists today."""
from typing import Optional

import config
from ai.market_intelligence.providers.base import BaseCrossAssetProvider
from ai.market_intelligence.providers.mock import MockCrossAssetProvider

_PROVIDERS = {"mock": MockCrossAssetProvider}


def get_cross_asset_provider(name: Optional[str] = None) -> BaseCrossAssetProvider:
    provider_name = (name or config.MARKET_INTEL_CROSS_ASSET_PROVIDER or "mock").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown MARKET_INTEL_CROSS_ASSET_PROVIDER '{provider_name}'. "
            f"Valid options: {', '.join(_PROVIDERS)}."
        )
    return provider_cls()
