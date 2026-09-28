"""Anthropic Claude provider — the default (AI_PROVIDER=anthropic). Reads
its API key and model from config (never hardcoded; see config.py's
AI_API_KEY / AI_MODEL, sourced from the environment). The 'anthropic'
package is imported lazily/guarded so its absence — e.g. a dev machine that
hasn't installed api/requirements.txt yet — degrades to a clear
ProviderConfigError instead of an ImportError crashing the whole API
process at startup.

Stage 6: when `tools` is passed to chat(), it's forwarded to the Messages
API as-is (see ai/tools/registry.py::to_provider_format(), which already
targets this exact `{name, description, input_schema}` shape). A
`stop_reason` of "tool_use" surfaces as ToolCall entries on the response;
the caller (ai/assistant.py) is responsible for executing them and feeding
the results back via the generic message shapes translated in
_to_anthropic_messages() below.
"""
import json
from typing import List, Optional

import config
from ai.providers.base import (
    BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse, ProviderResponseError, ToolCall,
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

    def chat(self, system: str, messages: List[dict], tools: Optional[List[dict]] = None) -> ProviderResponse:
        kwargs = dict(
            model=self.model,
            max_tokens=config.AI_MAX_TOKENS,
            system=system,
            messages=_to_anthropic_messages(messages),
        )
        if tools:
            kwargs["tools"] = tools

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:  # the SDK's own exception hierarchy (APIError, APIConnectionError, ...) —
            # never let a raw SDK exception reach the API route; it always becomes a typed provider error.
            raise ProviderRequestError(str(exc)) from exc

        text = _extract_text(response)
        # Only parsed when tools were actually offered this call — a
        # tool_use block appearing when none were offered is unexpected,
        # malformed content, not a real tool request (same treatment as an
        # empty response, below).
        tool_calls = _extract_tool_calls(response) if tools else []
        if not text and not tool_calls:
            raise ProviderResponseError("Provider returned an empty or unreadable response.")
        return ProviderResponse(
            text=text, provider=self.name, model=self.model,
            tool_calls=tool_calls, raw_content=getattr(response, "content", None),
        )


def _extract_text(response) -> str:
    blocks = getattr(response, "content", None) or []
    parts = [getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"]
    return "\n".join(p for p in parts if p).strip()


def _extract_tool_calls(response) -> List[ToolCall]:
    blocks = getattr(response, "content", None) or []
    return [
        ToolCall(id=b.id, name=b.name, arguments=dict(getattr(b, "input", None) or {}))
        for b in blocks if getattr(b, "type", None) == "tool_use"
    ]


def _to_anthropic_messages(messages: List[dict]) -> List[dict]:
    """Translates ai/assistant.py's provider-agnostic message list into
    Anthropic's wire format. Plain user/assistant text turns pass through
    unchanged; a `{"role": "tool_result", ...}` entry becomes a `user`
    message carrying a `tool_result` content block (Anthropic has no `tool`
    role); an assistant turn that requested tool calls replays its stored
    `raw_content` (the exact original content blocks) verbatim, since a
    reconstruction from ToolCall alone isn't guaranteed to round-trip."""
    out = []
    for m in messages:
        role = m.get("role")
        if role == "tool_result":
            content = m.get("content")
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id"),
                    "content": content if isinstance(content, str) else json.dumps(content),
                }],
            })
        elif role == "assistant" and m.get("tool_calls") is not None:
            out.append({"role": "assistant", "content": m.get("content")})
        else:
            out.append({"role": role, "content": m.get("content")})
    return out
