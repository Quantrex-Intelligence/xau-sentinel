"""Tests for the provider abstraction (ai/providers/). Covers the mock
provider, the factory's provider selection, and the Anthropic provider's
failure modes — all without a real network call or a real API key, so this
suite runs the same in CI as it does locally."""
from types import SimpleNamespace

import pytest

import config
from ai.providers import get_provider
from ai.providers.base import ProviderConfigError, ProviderRequestError, ProviderResponseError
from ai.providers.mock_provider import MockProvider
from ai.providers import anthropic_provider
from ai.providers import groq_provider


def test_mock_provider_is_deterministic_and_offline():
    provider = MockProvider()
    system = "SYSTEM\n\nCONTEXT (the only facts...): ### Market Structure ###\nPrice: 100"
    messages = [{"role": "user", "content": "What is the current price?"}]

    r1 = provider.chat(system, messages)
    r2 = provider.chat(system, messages)

    assert r1.text == r2.text  # deterministic, no hidden randomness or clock dependence
    assert r1.provider == "mock"
    assert "What is the current price?" in r1.text
    assert "MOCK PROVIDER" in r1.text  # never presented as if it were a real model's answer


def test_get_provider_selects_mock_when_configured(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "mock")
    provider = get_provider()
    assert isinstance(provider, MockProvider)


def test_get_provider_override_beats_config(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    provider = get_provider("mock")
    assert isinstance(provider, MockProvider)


def test_get_provider_raises_config_error_for_unknown_provider_name(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "not-a-real-provider")
    with pytest.raises(ProviderConfigError, match="anthropic, groq, mock"):
        get_provider()


def test_anthropic_provider_raises_config_error_when_package_missing(monkeypatch):
    monkeypatch.setattr(anthropic_provider, "anthropic", None)
    monkeypatch.setattr(config, "AI_API_KEY", "irrelevant")
    with pytest.raises(ProviderConfigError, match="not installed"):
        anthropic_provider.AnthropicProvider()


def test_anthropic_provider_raises_config_error_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    with pytest.raises(ProviderConfigError, match="AI_API_KEY"):
        anthropic_provider.AnthropicProvider()


def _fake_anthropic_module(monkeypatch, fake_client):
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_MODEL", "test-model")
    fake_module = SimpleNamespace(Anthropic=lambda api_key: fake_client)
    monkeypatch.setattr(anthropic_provider, "anthropic", fake_module)


class _FakeBlock:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._result


def test_anthropic_provider_returns_text_on_success(monkeypatch):
    fake_client = SimpleNamespace(messages=_FakeMessages(
        result=_FakeResponse([_FakeBlock("text", "hello from claude")])
    ))
    _fake_anthropic_module(monkeypatch, fake_client)

    provider = anthropic_provider.AnthropicProvider()
    response = provider.chat("system prompt", [{"role": "user", "content": "hi"}])

    assert response.text == "hello from claude"
    assert response.provider == "anthropic"
    assert response.model == "test-model"


def test_anthropic_provider_wraps_sdk_exception_as_request_error(monkeypatch):
    fake_client = SimpleNamespace(messages=_FakeMessages(exc=RuntimeError("connection reset")))
    _fake_anthropic_module(monkeypatch, fake_client)

    provider = anthropic_provider.AnthropicProvider()
    with pytest.raises(ProviderRequestError, match="connection reset"):
        provider.chat("system prompt", [{"role": "user", "content": "hi"}])


def test_anthropic_provider_raises_response_error_on_empty_content(monkeypatch):
    fake_client = SimpleNamespace(messages=_FakeMessages(result=_FakeResponse([])))
    _fake_anthropic_module(monkeypatch, fake_client)

    provider = anthropic_provider.AnthropicProvider()
    with pytest.raises(ProviderResponseError):
        provider.chat("system prompt", [{"role": "user", "content": "hi"}])


def test_anthropic_provider_raises_response_error_on_non_text_blocks_only(monkeypatch):
    """A malformed/unexpected response shape (e.g. only a tool_use block,
    no text) must be treated the same as empty — never returned as-is."""
    fake_client = SimpleNamespace(messages=_FakeMessages(
        result=_FakeResponse([_FakeBlock("tool_use", None)])
    ))
    _fake_anthropic_module(monkeypatch, fake_client)

    provider = anthropic_provider.AnthropicProvider()
    with pytest.raises(ProviderResponseError):
        provider.chat("system prompt", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Groq (mirrors the Anthropic tests above, same fake-SDK-object style)
# ---------------------------------------------------------------------------

def test_groq_provider_raises_config_error_when_package_missing(monkeypatch):
    monkeypatch.setattr(groq_provider, "groq", None)
    monkeypatch.setattr(config, "AI_API_KEY", "irrelevant")
    with pytest.raises(ProviderConfigError, match="not installed"):
        groq_provider.GroqProvider()


def test_groq_provider_raises_config_error_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(groq_provider, "groq", SimpleNamespace(Groq=lambda api_key: None))
    monkeypatch.setattr(config, "AI_API_KEY", "")
    with pytest.raises(ProviderConfigError, match="AI_API_KEY"):
        groq_provider.GroqProvider()


def _fake_groq_module(monkeypatch, fake_client):
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_MODEL", "test-model")
    fake_module = SimpleNamespace(Groq=lambda api_key: fake_client)
    monkeypatch.setattr(groq_provider, "groq", fake_module)


class _FakeToolCallFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeGroqToolCall:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = _FakeToolCallFunction(name, arguments)


class _FakeGroqMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeGroqChoice:
    def __init__(self, message):
        self.message = message


class _FakeGroqResponse:
    def __init__(self, message):
        self.choices = [_FakeGroqChoice(message)]


class _FakeGroqCompletions:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._result


def test_groq_provider_returns_text_on_success(monkeypatch):
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeGroqCompletions(
        result=_FakeGroqResponse(_FakeGroqMessage(content="hello from groq"))
    )))
    _fake_groq_module(monkeypatch, fake_client)

    provider = groq_provider.GroqProvider()
    response = provider.chat("system prompt", [{"role": "user", "content": "hi"}])

    assert response.text == "hello from groq"
    assert response.provider == "groq"
    assert response.model == "test-model"


def test_groq_provider_wraps_sdk_exception_as_request_error(monkeypatch):
    fake_client = SimpleNamespace(chat=SimpleNamespace(
        completions=_FakeGroqCompletions(exc=RuntimeError("connection reset"))
    ))
    _fake_groq_module(monkeypatch, fake_client)

    provider = groq_provider.GroqProvider()
    with pytest.raises(ProviderRequestError, match="connection reset"):
        provider.chat("system prompt", [{"role": "user", "content": "hi"}])


def test_groq_provider_raises_response_error_on_empty_content(monkeypatch):
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeGroqCompletions(
        result=_FakeGroqResponse(_FakeGroqMessage(content=""))
    )))
    _fake_groq_module(monkeypatch, fake_client)

    provider = groq_provider.GroqProvider()
    with pytest.raises(ProviderResponseError):
        provider.chat("system prompt", [{"role": "user", "content": "hi"}])


def test_groq_provider_parses_tool_call_arguments_from_json_string(monkeypatch):
    """Unlike Anthropic's `.input` dict, Groq/OpenAI's tool-call arguments
    arrive as a JSON string — must come back parsed on ToolCall."""
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeGroqCompletions(
        result=_FakeGroqResponse(_FakeGroqMessage(
            content=None,
            tool_calls=[_FakeGroqToolCall("call-1", "get_current_setup", '{"symbol": "XAUUSD"}')],
        ))
    )))
    _fake_groq_module(monkeypatch, fake_client)

    provider = groq_provider.GroqProvider()
    response = provider.chat(
        "system prompt", [{"role": "user", "content": "hi"}],
        tools=[{"name": "get_current_setup", "description": "d", "input_schema": {}}],
    )

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].name == "get_current_setup"
    assert response.tool_calls[0].arguments == {"symbol": "XAUUSD"}


def test_to_groq_tools_wraps_registry_shape_into_openai_function_shape():
    tools = [{"name": "get_price", "description": "Current price", "input_schema": {"type": "object"}}]
    wrapped = groq_provider._to_groq_tools(tools)
    assert wrapped == [{
        "type": "function",
        "function": {"name": "get_price", "description": "Current price", "parameters": {"type": "object"}},
    }]


def test_to_groq_messages_puts_system_in_the_messages_list():
    out = groq_provider._to_groq_messages("SYSTEM TEXT", [{"role": "user", "content": "hi"}])
    assert out[0] == {"role": "system", "content": "SYSTEM TEXT"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_to_groq_messages_translates_tool_result_to_tool_role():
    out = groq_provider._to_groq_messages("SYS", [
        {"role": "tool_result", "tool_call_id": "call-1", "content": "42"},
    ])
    assert out[1] == {"role": "tool", "tool_call_id": "call-1", "content": "42"}


def test_get_provider_raises_config_error_for_groq_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "groq")
    monkeypatch.setattr(config, "AI_API_KEY", "")
    with pytest.raises(ProviderConfigError, match="AI_API_KEY"):
        get_provider()
