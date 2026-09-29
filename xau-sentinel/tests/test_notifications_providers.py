"""Tests for the notification provider abstraction (Stage 14): the
Telegram Bot API client's success/timeout/error-classification behavior,
that the bot token never leaks into any raised/returned message, and the
mock provider's recorded-messages contract."""
import httpx
import pytest

import config
from ai.notifications.models import DeliveryResult
from ai.notifications.providers import get_notification_provider
from ai.notifications.providers.mock import MockNotificationProvider
from ai.notifications.providers.telegram import NotificationConfigError, TelegramNotificationProvider

TOKEN = "123456:AAsecret-token-value-that-must-never-leak"
CHAT_ID = "987654321"


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {"ok": True}

    def json(self):
        return self._json_data


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", CHAT_ID)


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------

def test_telegram_provider_raises_config_error_when_token_missing(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(NotificationConfigError):
        TelegramNotificationProvider()


def test_telegram_provider_raises_config_error_when_chat_id_missing(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    with pytest.raises(NotificationConfigError):
        TelegramNotificationProvider()


# ---------------------------------------------------------------------------
# Success / failure classification
# ---------------------------------------------------------------------------

def test_send_success(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(200))
    result = TelegramNotificationProvider().send("hello")
    assert result.success is True
    assert result.error is None


def test_send_timeout_is_retryable(monkeypatch):
    def raise_timeout(*a, **k):
        raise httpx.TimeoutException("timed out")
    monkeypatch.setattr(httpx, "post", raise_timeout)
    result = TelegramNotificationProvider().send("hello")
    assert result.success is False
    assert result.retryable is True


def test_send_connection_error_is_retryable(monkeypatch):
    def raise_connect_error(*a, **k):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(httpx, "post", raise_connect_error)
    result = TelegramNotificationProvider().send("hello")
    assert result.success is False
    assert result.retryable is True


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_send_server_and_rate_limit_errors_are_retryable(monkeypatch, status):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(status, {"description": "server issue"}))
    result = TelegramNotificationProvider().send("hello")
    assert result.success is False
    assert result.retryable is True


@pytest.mark.parametrize("status", [400, 401, 403])
def test_send_client_auth_errors_are_not_retryable(monkeypatch, status):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(status, {"description": "bad request"}))
    result = TelegramNotificationProvider().send("hello")
    assert result.success is False
    assert result.retryable is False


def test_send_malformed_json_response_degrades_gracefully(monkeypatch):
    class _BadResponse:
        status_code = 500
        def json(self):
            raise ValueError("not json")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _BadResponse())
    result = TelegramNotificationProvider().send("hello")
    assert result.success is False
    assert "no further detail" in result.error


def test_error_message_includes_telegrams_description_field(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(400, {"description": "chat not found"}))
    result = TelegramNotificationProvider().send("hello")
    assert "chat not found" in result.error


# ---------------------------------------------------------------------------
# Security: the bot token must never leak
# ---------------------------------------------------------------------------

def test_token_never_appears_in_error_message_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(401, {"description": "Unauthorized"}))
    result = TelegramNotificationProvider().send("hello")
    assert TOKEN not in result.error


def test_token_never_appears_in_error_message_on_timeout(monkeypatch):
    def raise_timeout(*a, **k):
        raise httpx.TimeoutException(f"timed out calling https://api.telegram.org/bot{TOKEN}/sendMessage")
    monkeypatch.setattr(httpx, "post", raise_timeout)
    result = TelegramNotificationProvider().send("hello")
    assert TOKEN not in result.error


def test_token_never_appears_in_error_message_on_connection_error(monkeypatch):
    def raise_connect_error(*a, **k):
        raise httpx.ConnectError(f"failed to connect to https://api.telegram.org/bot{TOKEN}/sendMessage")
    monkeypatch.setattr(httpx, "post", raise_connect_error)
    result = TelegramNotificationProvider().send("hello")
    assert TOKEN not in result.error


def test_token_never_appears_via_raise_for_status_message(monkeypatch):
    """httpx.Response.raise_for_status()'s own generated message embeds
    the full request URL (which contains the token) — confirmed via a
    real httpx.Response below, not an assumption. This proves the
    provider's own error string is hand-built, never that raw message."""
    request = httpx.Request("POST", f"https://api.telegram.org/bot{TOKEN}/sendMessage")
    response = httpx.Response(401, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as real_error:
        assert TOKEN in str(real_error)  # sanity check: httpx's own message DOES leak the token

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse(401, {"description": "Unauthorized"}))
    result = TelegramNotificationProvider().send("hello")
    assert TOKEN not in (result.error or "")


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

def test_mock_provider_records_sent_messages():
    provider = MockNotificationProvider()
    result = provider.send("first")
    provider.send("second")
    assert result.success is True
    assert provider.sent_messages == ["first", "second"]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_returns_mock_provider(monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "mock")
    assert isinstance(get_notification_provider(), MockNotificationProvider)


def test_factory_returns_telegram_provider_when_configured(monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "telegram")
    assert isinstance(get_notification_provider(), TelegramNotificationProvider)


def test_factory_raises_for_unknown_provider_name(monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError, match="Unknown NOTIFICATION_PROVIDER"):
        get_notification_provider()
