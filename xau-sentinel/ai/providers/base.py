"""Provider abstraction — this is the one seam ai/assistant.py depends on,
so the LLM backend can be swapped (or mocked in tests) without touching
orchestration, context building, or the API routes. Every provider takes the
same (system, messages) shape and returns the same ProviderResponse, or
raises one of the typed errors below so the API layer can map a failure to
the right HTTP status instead of a bare 500.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


class ProviderError(Exception):
    """Base for every provider failure — callers that don't care about the
    distinction can catch just this."""


class ProviderConfigError(ProviderError):
    """No provider configured, or configured incompletely (missing SDK,
    missing API key). The caller must show a clear setup message, never a
    crash — see the Stage 3 spec's "clear configuration error" rule."""


class ProviderRequestError(ProviderError):
    """The provider was reachable in principle but this particular request
    failed: network error, auth rejected, rate limit, timeout."""


class ProviderResponseError(ProviderError):
    """The provider replied, but not in a shape this app can use (empty
    content, missing text blocks, unexpected structure)."""


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str


class BaseProvider(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    def chat(self, system: str, messages: List[dict]) -> ProviderResponse:
        """`messages` is provider-agnostic: a list of
        {"role": "user" | "assistant", "content": str} in chronological
        order. `system` carries the safety rules and the deterministic
        context block — see ai/prompts.py."""
        raise NotImplementedError
