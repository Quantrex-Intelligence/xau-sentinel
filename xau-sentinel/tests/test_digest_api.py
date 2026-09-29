"""API-level tests for /api/digest/{...} — /status never returns Telegram
secrets, /preview never writes anything, /send is idempotent per period
(a second call reports already_sent without a second provider call)."""
import inspect

import pytest
from fastapi.testclient import TestClient

from ai.digest import store as digest_store
from ai.notifications.providers.mock import MockNotificationProvider
from api.main import app


@pytest.fixture
def api_client(temp_db):
    digest_store.init_table()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def closed_trade_id(api_client):
    from journal import trades as trades_repo
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-09-28", "trade_time": "10:00", "symbol": "XAUUSD", "direction": "BUY",
         "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0, "planned_rr": 3.0},
        {"h1_bias": "BULLISH", "liquidity": "Previous Day Low swept", "mss": "Bullish", "displacement": "Bullish"},
    )
    trades_repo.close_trade(trade_id, {"exit_price": 3730.0, "result": "WIN", "pnl": 300.0,
                                        "r_multiple": 3.0, "duration_minutes": 45})
    return trade_id


def test_status_never_returns_bot_token_or_chat_id(api_client, monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.setattr("config.TELEGRAM_CHAT_ID", "123456")
    resp = api_client.get("/api/digest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "super-secret-token" not in str(body)
    assert "123456" not in str(body)
    assert body["configured"] is True


def test_preview_returns_a_digest_without_sending(api_client, closed_trade_id):
    resp = api_client.post("/api/digest/preview", json={"digest_type": "WEEKLY"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["digest_type"] == "WEEKLY"
    assert "overview" in body


def test_preview_400s_for_an_unknown_digest_type(api_client):
    resp = api_client.post("/api/digest/preview", json={"digest_type": "DAILY"})
    assert resp.status_code == 400


def test_preview_never_writes_to_digest_deliveries_or_any_journal_table(api_client, closed_trade_id):
    from journal.database import get_connection

    def _snapshot():
        with get_connection() as conn:
            trade = dict(conn.execute("SELECT * FROM trades WHERE id = ?", (closed_trade_id,)).fetchone())
            deliveries = conn.execute("SELECT * FROM digest_deliveries").fetchall()
            return trade, [dict(r) for r in deliveries]

    before = _snapshot()
    api_client.post("/api/digest/preview", json={"digest_type": "WEEKLY"})
    after = _snapshot()
    assert before == after


def test_preview_route_never_calls_a_provider_or_the_store_structurally():
    import api.routes.digest as route_mod
    source = inspect.getsource(route_mod.preview_digest)
    for banned in ("get_notification_provider", "record_sent", "attempt_send"):
        assert banned not in source


def test_send_delivers_once_and_records_it(api_client, closed_trade_id, monkeypatch):
    shared_provider = MockNotificationProvider()
    monkeypatch.setattr("ai.digest.service.get_notification_provider", lambda: shared_provider)

    resp = api_client.post("/api/digest/send", json={"digest_type": "WEEKLY"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is True
    assert body["already_sent"] is False
    assert len(shared_provider.sent_messages) == 1
    assert "XAU Sentinel" in shared_provider.sent_messages[0]


def test_send_is_idempotent_for_the_same_period(api_client, closed_trade_id, monkeypatch):
    shared_provider = MockNotificationProvider()
    monkeypatch.setattr("ai.digest.service.get_notification_provider", lambda: shared_provider)

    api_client.post("/api/digest/send", json={"digest_type": "WEEKLY"})
    resp = api_client.post("/api/digest/send", json={"digest_type": "WEEKLY"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is False
    assert body["already_sent"] is True
    assert len(shared_provider.sent_messages) == 1  # the provider was never called a second time


def test_send_400s_for_an_unknown_digest_type(api_client):
    resp = api_client.post("/api/digest/send", json={"digest_type": "YEARLY"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Stage 20 VAL-004: /preview and /send must use identical period semantics
# -- both route through service.build_digest() with no reference override,
# never a second implementation.
# ---------------------------------------------------------------------------

def test_preview_and_send_report_identical_period_bounds(api_client, closed_trade_id, monkeypatch):
    shared_provider = MockNotificationProvider()
    monkeypatch.setattr("ai.digest.service.get_notification_provider", lambda: shared_provider)

    preview_body = api_client.post("/api/digest/preview", json={"digest_type": "WEEKLY"}).json()
    send_body = api_client.post("/api/digest/send", json={"digest_type": "WEEKLY"}).json()

    assert preview_body["period_start"] == send_body["summary"]["period_start"]
    assert preview_body["period_end"] == send_body["summary"]["period_end"]
