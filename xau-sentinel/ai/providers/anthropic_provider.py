"""Anthropic Claude provider — the default (AI_PROVIDER=anthropic). Reads
its API key and model from config (never hardcoded; see config.py's
AI_API_KEY / AI_MODEL, sourced from the environment). The 'anthropic'
package is imported lazily/guarded so its absence — e.g. a dev machine that
hasn't installed api/requirements.txt yet — degrades to a clear
ProviderConfigError instead of an ImportError crashing the whole API
process at startup.
"""
from typing import List

import config
from ai.providers.base import (
    BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse, ProviderResponseError,
)

try:
    import anthropic
except ImportError:
    anthropic = None


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self):
        if anthropic is None:
            raise ProviderConfigError(
                "The 'anthropic' package is not installed. Run `pip install -r api/requirements.txt`, "
                "or set AI_PROVIDER=mock to use the offline provider instead."
            )
        if not config.AI_API_KEY:
            raise ProviderConfigError(
                "AI_API_KEY is not set. Set AI_PROVIDER=anthropic and AI_API_KEY in your environment/.env "
                "(see .env.example), or set AI_PROVIDER=mock to use the offline provider instead."
            )
        self._client = anthropic.Anthropic(api_key=config.AI_API_KEY)
        self.model = config.AI_MODEL

    def chat(self, system: str, messages: List[dict]) -> ProviderResponse:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=config.AI_MAX_TOKENS,
                system=system,
                messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            )
        except Exception as exc:  # the SDK's own exception hierarchy (APIError, APIConnectionError, ...) —
            # never let a raw SDK exception reach the API route; it always becomes a typed provider error.
            raise ProviderRequestError(str(exc)) from exc

        text = _extract_text(response)
        if not text:
            raise ProviderResponseError("Provider returned an empty or unreadable response.")
        return ProviderResponse(text=text, provider=self.name, model=self.model)


def _extract_text(response) -> str:
    blocks = getattr(response, "content", None) or []
    parts = [getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p).strip()
