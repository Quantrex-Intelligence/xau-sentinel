"""Groq provider (AI_PROVIDER=groq). Reads its API key and model from the
same config.AI_API_KEY / config.AI_MODEL as every other provider (see
config.py) — there is nothing Anthropic-specific about those names, so
switching AI_PROVIDER just points them at a different vendor's key/model.
AI_MODEL's own default is an Anthropic model name; it means nothing to
Groq, so it isn't silently substituted here — set AI_MODEL to a real Groq
model (e.g. "llama-3.3-70b-versatile") when using this provider, and a
wrong name surfaces as Groq's own clear "model not found" error rather
than a fallback that quietly does the wrong thing.

Groq's chat-completions API is OpenAI-compatible, so this uses the
official 'groq' package (mirroring the OpenAI wire shape) rather than the
'openai' package pointed at a different base URL — one clear SDK per
vendor, the same convention anthropic_provider.py already sets. Lazily
imported/guarded the same way, so a dev machine without it degrades to a
clear ProviderConfigError, never an ImportError crashing the whole API
process at startup.

The registry's to_provider_format() (ai/tools/registry.py) targets
Anthropic's flat {name, description, input_schema} tool shape — this file
translates that into Groq/OpenAI's nested {"type": "function", "function":
{...}} shape privately, in _to_groq_tools(), rather than changing the
shared registry: the Anthropic path is untouched either way.
"""
import json
from typing import List, Optional

import config
from ai.providers.base import (
    BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse, ProviderResponseError, ToolCall,
)

try:
    import groq
except ImportError:
    groq = None


class GroqProvider(BaseProvider):
    name = "groq"

    def __init__(self):
        if groq is None:
            raise ProviderConfigError(
                "The 'groq' package is not installed. Run `pip install -r api/requirements.txt`, "
                "or set AI_PROVIDER=mock to use the offline provider instead."
            )
        if not config.AI_API_KEY:
            raise ProviderConfigError(
                "AI_API_KEY is not set. Set AI_PROVIDER=groq and AI_API_KEY in your environment/.env "
                "(see .env.example) to a Groq API key, or set AI_PROVIDER=mock to use the offline provider "
                "instead."
            )
        self._client = groq.Groq(api_key=config.AI_API_KEY)
        self.model = config.AI_MODEL

    def chat(self, system: str, messages: List[dict], tools: Optional[List[dict]] = None) -> ProviderResponse:
        kwargs = dict(
            model=self.model,
            max_tokens=config.AI_MAX_TOKENS,
            messages=_to_groq_messages(system, messages),
        )
        if tools:
            kwargs["tools"] = _to_groq_tools(tools)

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # the SDK's own exception hierarchy — never let it reach the API route raw.
            raise ProviderRequestError(str(exc)) from exc

        message = response.choices[0].message
        text = (message.content or "").strip()
        tool_calls = _extract_tool_calls(message) if tools else []
        if not text and not tool_calls:
            raise ProviderResponseError("Provider returned an empty or unreadable response.")
        return ProviderResponse(text=text, provider=self.name, model=self.model, tool_calls=tool_calls, raw_content=message)


def _extract_tool_calls(message) -> List[ToolCall]:
    calls = getattr(message, "tool_calls", None) or []
    result = []
    for c in calls:
        try:
            arguments = json.loads(c.function.arguments) if c.function.arguments else {}
        except (TypeError, ValueError):
            arguments = {}
        result.append(ToolCall(id=c.id, name=c.function.name, arguments=arguments))
    return result


def _to_groq_tools(tools: List[dict]) -> List[dict]:
    """The registry's Anthropic-shaped {name, description, input_schema}
    tool specs, wrapped into OpenAI/Groq's nested function-calling shape."""
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"],
        }}
        for t in tools
    ]


def _to_groq_messages(system: str, messages: List[dict]) -> List[dict]:
    """Groq/OpenAI put the system prompt in the messages list itself
    (unlike Anthropic's separate top-level `system` param); a `tool_result`
    entry becomes a `tool` role message.

    An assistant turn that requested tool calls replays this provider's own
    prior-turn message object, exactly the way anthropic_provider.py's
    _to_anthropic_messages() replays its own raw content: ai/assistant.py
    stores ProviderResponse.raw_content under the message dict's `content`
    key (see ai/assistant.py's tool round-trip loop:
    `"content": response.raw_content if response.raw_content is not None
    else response.text`) — never a separate `raw_content` key — so `m["content"]`
    here is this provider's own Groq `message` object from chat()'s
    `raw_content=message`, not text."""
    out = [{"role": "system", "content": system}]
    for m in messages:
        role = m.get("role")
        if role == "tool_result":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id"),
                "content": m["content"] if isinstance(m.get("content"), str) else json.dumps(m.get("content")),
            })
        elif role == "assistant" and m.get("tool_calls") is not None:
            raw = m.get("content")  # this provider's own Groq message object, not text — see docstring above
            out.append({
                "role": "assistant",
                "content": getattr(raw, "content", None),
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in (getattr(raw, "tool_calls", None) or [])
                ],
            })
        else:
            out.append({"role": role, "content": m.get("content")})
    return out
