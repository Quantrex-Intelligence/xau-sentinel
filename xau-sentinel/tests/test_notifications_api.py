"""API-level tests for /api/notifications/telegram/{status,test} — thin
pass-throughs; never returns TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID in any
response, and the test endpoint 404s when Telegram isn't configured."""
import inspect

import pytest
from fastapi.testclient import TestClient

import config
from ai.notifications import store
from ai.notifications.delivery import CHANNEL
from api.main import app

TOKEN = "123456:secret-token-value"
CHAT_ID = "987654321"


@pytest.fixture
def api_client(temp_db):
    store.init_table()
    with TestClient(app) as client:
        yield client


def test_status_reports_not_configured_when_token_and_chat_id_are_unset(api_client, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    resp = api_client.get("/api/notifications/telegram/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["enabled"] == config.TELEGRAM_ENABLED


def test_status_reports_configured_when_both_are_set(api_client, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", CHAT_ID)
    resp = api_client.get("/api/notifications/telegram/status")
    assert resp.json()["configured"] is True


def test_status_never_includes_the_bot_token_or_chat_id(api_client, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", CHAT_ID)
    resp = api_client.get("/api/notifications/telegram/status")
    body_text = resp.text
    assert TOKEN not in body_text
    assert CHAT_ID not in body_text
    assert set(resp.json().keys()) == {"enabled", "configured", "provider", "last_success_at", "last_error_at"}


def test_status_reflects_last_success_and_error_from_deliveries(api_client, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", CHAT_ID)
    d1 = store.create_pending(1, CHANNEL)
    store.mark_sent(d1.id)
    d2 = store.create_pending(2, CHANNEL)
    store.mark_failed(d2.id, "boom")

    resp = api_client.get("/api/notifications/telegram/status")
    body = resp.json()
    assert body["last_success_at"] is not None
    assert body["last_error_at"] is not None


def test_test_endpoint_404s_when_telegram_provider_is_not_configured(api_client, monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "telegram")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    resp = api_client.post("/api/notifications/telegram/test")
    assert resp.status_code == 404


def test_test_endpoint_succeeds_with_the_mock_provider(api_client, monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "mock")
    resp = api_client.post("/api/notifications/telegram/test")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_test_endpoint_response_never_includes_the_token(api_client, monkeypatch):
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "mock")
    resp = api_client.post("/api/notifications/telegram/test")
    assert TOKEN not in resp.text


def test_notifications_routes_never_touch_trades_or_the_deterministic_engines():
    import api.routes.notifications as notifications_route
    source = inspect.getsource(notifications_route)
    for banned in (
        "trades_repo", "journal.trades", "evaluate_deterministic", "evaluate_current_setup",
        "detect_setup", "compute_status",
    ):
        assert banned not in source
