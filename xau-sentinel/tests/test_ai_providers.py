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
    with pytest.raises(ProviderConfigError):
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
