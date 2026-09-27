"""FastAPI layer tests. Every assertion compares the API response to calling
the underlying Python engine function directly (or exercises the full round
trip through the real journal DB) — proving the API is a thin, faithful
pass-through with no duplicated or drifted trading logic, per the UI
migration's non-negotiable rule."""
import pytest
from fastapi.testclient import TestClient

import config
from mt5 import market_data
from analysis.structure import analyze_structure
from analysis.zones import compute_zones
from analysis.regime import classify_regime
from analysis.setup import detect_setup

from api.main import app


@pytest.fixture
def api_client(temp_db):
    """A TestClient bound to the same isolated per-test DB as the journal
    tests use, so API tests never touch the developer's real data/*.db."""
    with TestClient(app) as client:
        yield client


def test_health(api_client):
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ticker_is_mock_and_matches_price_source(api_client):
    resp = api_client.get("/api/market/ticker")
    assert resp.status_code == 200
    body = resp.json()
    direct = market_data.get_price_info()
    assert body["source"] == direct["source"] == "mock"
    assert body["price"] == direct["price"]
    assert body["stale"] is False


def test_candles_endpoint_matches_get_candles_shape(api_client):
    resp = api_client.get("/api/market/candles", params={"timeframe": "M5", "count": 50})
    assert resp.status_code == 200
    body = resp.json()
    direct = market_data.get_candles("M5", 50)
    assert len(body) == len(direct) == 50
    assert body[-1]["close"] == pytest.approx(float(direct["close"].iloc[-1]))


def test_candles_endpoint_rejects_unsupported_timeframe(api_client):
    resp = api_client.get("/api/market/candles", params={"timeframe": "W1"})
    assert resp.status_code == 400


def test_structure_endpoint_matches_analyze_structure(api_client):
    resp = api_client.get("/api/market/structure")
    assert resp.status_code == 200
    body = resp.json()
    candles = market_data.get_all_candles(300)
    for tf in market_data.TIMEFRAMES:
        direct = analyze_structure(candles[tf])
        assert body[tf]["state"] == direct.state
        assert body[tf]["reason"] == direct.reason


def test_zones_endpoint_matches_compute_zones(api_client):
    resp = api_client.get("/api/market/zones")
    assert resp.status_code == 200
    candles = market_data.get_all_candles(300)
    direct = compute_zones(candles["M5"], candles["H1"], candles["H4"])
    assert resp.json() == direct


def test_regime_endpoint_matches_classify_regime(api_client):
    resp = api_client.get("/api/market/regime")
    assert resp.status_code == 200
    candles = market_data.get_all_candles(300)
    direct = classify_regime(candles["H1"], candles["M15"])
    assert resp.json()["regime"] == direct.regime


def test_setup_current_matches_detect_setup(api_client):
    resp = api_client.get("/api/setup/current")
    assert resp.status_code == 200
    candles = market_data.get_all_candles(300)
    direct = detect_setup(candles)
    body = resp.json()
    assert body["state"] == direct.state
    assert body["direction"] == direct.direction
    # NO-SETUP-without-H1-bias legitimately returns "WAITING" strings, not
    # bools — see api/schemas.py's SetupOut.checklist comment. Assert the
    # API preserves whatever shape the engine actually returned.
    assert body["checklist"] == direct.checklist


def test_analysis_snapshot_has_expected_shape(api_client):
    resp = api_client.get("/api/market/analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {
        "connection", "price", "structure", "regime", "zones", "liquidity",
        "setup", "risk", "session",
    }
    assert body["connection"]["mode"] == "mock"
    assert set(body["structure"].keys()) == set(market_data.TIMEFRAMES)


def test_risk_endpoint_matches_config_and_today_r_total(api_client):
    resp = api_client.get("/api/risk")
    assert resp.status_code == 200
    body = resp.json()
    assert body["balance"] == config.ACCOUNT_BALANCE
    assert body["risk_per_trade_pct"] == config.RISK_PER_TRADE_PCT
    assert body["today_r"] == 0.0  # isolated temp DB, no trades yet


def test_alerts_and_events_start_empty(api_client):
    assert api_client.get("/api/alerts").json() == []
    assert api_client.get("/api/events").json() == []


def test_journal_full_trade_lifecycle_via_api(api_client):
    create_resp = api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "10:00:00", "direction": "BUY",
        "entry": 3740.0, "stop_loss": 3735.0, "take_profit": 3750.0, "planned_rr": 2.0,
        "setup": "Sweep + MSS", "notes": "api test trade",
    })
    assert create_resp.status_code == 200
    trade = create_resp.json()
    assert trade["status"] == "OPEN"
    assert trade["notes"] == "api test trade"
    assert trade["h4_bias"] is not None  # context auto-captured, same as app.py's flow
    trade_id = trade["id"]

    get_resp = api_client.get(f"/api/journal/trades/{trade_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == trade_id

    close_resp = api_client.patch(f"/api/journal/trades/{trade_id}/close", json={
        "exit_price": 3750.0, "result": "WIN", "r_multiple": 2.0, "pnl": 200.0,
    })
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "CLOSED"
    assert close_resp.json()["result"] == "WIN"

    analytics_resp = api_client.get("/api/journal/analytics")
    assert analytics_resp.status_code == 200
    stats = analytics_resp.json()
    assert stats["total_trades"] == 1
    assert stats["wins"] == 1
    assert stats["total_r"] == 2.0


def test_close_unknown_trade_returns_404(api_client):
    resp = api_client.patch("/api/journal/trades/9999/close", json={
        "exit_price": 100.0, "result": "WIN",
    })
    assert resp.status_code == 404


def test_get_unknown_trade_returns_404(api_client):
    resp = api_client.get("/api/journal/trades/9999")
    assert resp.status_code == 404


def test_journal_filters_are_applied(api_client):
    api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "10:00:00", "direction": "BUY",
        "entry": 3740.0, "stop_loss": 3735.0,
    })
    api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "11:00:00", "direction": "SELL",
        "entry": 3740.0, "stop_loss": 3745.0,
    })
    resp = api_client.get("/api/journal/trades", params={"direction": "BUY"})
    assert resp.status_code == 200
    trades = resp.json()
    assert len(trades) == 1
    assert trades[0]["direction"] == "BUY"


def test_settings_endpoint_exposes_no_secrets(api_client):
    resp = api_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "mock"
    assert body["trading_symbol"] == config.TRADING_SYMBOL
    serialized = str(body).lower()
    for secret_field in ("login", "password", "server", "db_path"):
        assert secret_field not in serialized


def test_websocket_market_stream_sends_valid_snapshot(api_client):
    with api_client.websocket_connect("/ws/market") as ws:
        data = ws.receive_json()
        assert "setup" in data
        assert "connection" in data
        assert data["connection"]["mode"] == "mock"
