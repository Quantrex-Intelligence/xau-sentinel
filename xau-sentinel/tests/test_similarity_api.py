"""API-level tests for /api/similarity/*."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from journal import trades as trades_repo


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


def _trade_payload(**overrides):
    payload = {
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
        "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
        "take_profit": 110.0, "planned_rr": 2.5, "setup": "Sweep + MSS", "market_regime": "TRENDING UP",
        "notes": "", "screenshot_path": None,
    }
    payload.update(overrides)
    return payload


def _context_payload(**overrides):
    context = {
        "h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
        "regime": "TRENDING UP", "liquidity": "Previous Day Low swept", "mss": "Bullish",
        "displacement": "Bullish", "session": "London",
    }
    context.update(overrides)
    return context


def test_get_current_similarity_returns_200_in_mock_mode(api_client):
    resp = api_client.get("/api/similarity/current")
    assert resp.status_code == 200
    body = resp.json()
    assert "query_features" in body
    assert "matches" in body


def test_get_trade_similarity_returns_404_for_unknown_id(api_client):
    resp = api_client.get("/api/similarity/trade/999999")
    assert resp.status_code == 404


def test_get_trade_similarity_finds_other_trades(api_client):
    query_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    other_id = trades_repo.create_trade(_trade_payload(), _context_payload())

    resp = api_client.get(f"/api/similarity/trade/{query_id}", params={"min_similarity": 0.0})
    assert resp.status_code == 200
    body = resp.json()
    trade_ids = {m["trade_id"] for m in body["matches"]}
    assert other_id in trade_ids
    assert query_id not in trade_ids


def test_similarity_response_never_contains_a_probability_field(api_client):
    trades_repo.create_trade(_trade_payload(), _context_payload())
    resp = api_client.get("/api/similarity/current", params={"min_similarity": 0.0})
    body_text = resp.text.lower()
    assert "probability" not in body_text
    assert "confidence" not in body_text
    assert "win_chance" not in body_text
