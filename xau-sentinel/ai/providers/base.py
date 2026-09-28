"""Provider abstraction — this is the one seam ai/assistant.py depends on,
so the LLM backend can be swapped (or mocked in tests) without touching
orchestration, context building, or the API routes. Every provider takes the
same (system, messages, tools) shape and returns the same ProviderResponse,
or raises one of the typed errors below so the API layer can map a failure
to the right HTTP status instead of a bare 500.

Stage 6 adds optional tool calling: `tools` defaults to None, so a provider
offered no tools (or one that doesn't support them) behaves exactly as it
did before Stage 6 — this is what keeps every pre-Stage-6 caller working
unchanged. See ai/tools/ for the tool registry and executor, and
ai/assistant.py for the round-trip loop that drives this.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
class ToolCall:
    """One tool the model asked to run, provider-agnostic. `id` round-trips
    back to the provider on the follow-up call so it can match the result to
    the request (Anthropic's tool_use_id linkage)."""
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    # Empty unless the provider was offered `tools` and chose to call one or
    # more of them instead of (or before) answering in text.
    tool_calls: List[ToolCall] = field(default_factory=list)
    # Opaque passthrough of whatever content the provider actually returned
    # (e.g. Anthropic's raw content-block list) — needed to replay an
    # assistant tool-use turn back to that same provider verbatim on the
    # next call, since a reconstruction from ToolCall alone can't guarantee
    # a byte-identical round trip. Never inspected outside the provider that
    # produced it.
    raw_content: Any = None


class BaseProvider(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    def chat(self, system: str, messages: List[dict], tools: Optional[List[dict]] = None) -> ProviderResponse:
        """`messages` is provider-agnostic: a list of
        {"role": "user" | "assistant", "content": str} in chronological
        order, plus two transient shapes used only within a single tool-
        calling turn (see ai/assistant.py): an assistant turn carrying
        `tool_calls`, and a `{"role": "tool_result", ...}` entry. `system`
        carries the safety rules and the deterministic context block — see
        ai/prompts.py. `tools`, when given, is a list of tool specs in the
        provider's own wire format (see ai/tools/registry.py); None means no
        tools were offered this call, and every provider must behave exactly
        as it did before tool calling existed in that case."""
        raise NotImplementedError
