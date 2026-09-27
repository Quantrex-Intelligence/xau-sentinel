"""Provider factory — the only place ai/assistant.py (and the /api/ai/config
route) needs to know about to add a new LLM backend later. Picks the
provider named by config.AI_PROVIDER unless the caller overrides it
explicitly (tests do this to force the mock provider regardless of the
environment).
"""
from typing import Optional

import config
from ai.providers.base import (
    BaseProvider, ProviderConfigError, ProviderError, ProviderRequestError,
    ProviderResponse, ProviderResponseError,
)
from ai.providers.mock_provider import MockProvider

__all__ = [
    "BaseProvider", "ProviderError", "ProviderConfigError", "ProviderRequestError",
    "ProviderResponseError", "ProviderResponse", "get_provider",
]

_NON_ANTHROPIC_PROVIDERS = {"mock": MockProvider}


def get_provider(name: Optional[str] = None) -> BaseProvider:
    provider_name = (name or config.AI_PROVIDER or "anthropic").strip().lower()

    if provider_name == "anthropic":
        # Imported lazily so a missing `anthropic` package only breaks the
        # anthropic path, never module import for the whole ai/ layer.
        from ai.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()

    provider_cls = _NON_ANTHROPIC_PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ProviderConfigError(
            f"Unknown AI_PROVIDER '{provider_name}'. Valid options: anthropic, mock."
        )
    return provider_cls()
