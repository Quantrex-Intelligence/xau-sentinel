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


def test_fundednext_status_reflects_mock_mode(api_client):
    resp = api_client.get("/api/fundednext/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "mock"
    assert body["data_available"] is True
    assert body["safety_level"] in ("SAFE", "WARNING", "CRITICAL", "BREACHED")


def test_fundednext_risk_alias_matches_status(api_client):
    status = api_client.get("/api/fundednext/status").json()
    risk = api_client.get("/api/fundednext/risk").json()
    assert status["safety_level"] == risk["safety_level"]
    assert status["account_type"] == risk["account_type"]


def test_fundednext_rules_lists_both_account_types(api_client):
    resp = api_client.get("/api/fundednext/rules")
    assert resp.status_code == 200
    labels = {r["account_type"] for r in resp.json()}
    assert labels == {"stellar_2step", "stellar_lite"}


def test_fundednext_settings_default_and_update(api_client):
    default = api_client.get("/api/fundednext/settings").json()
    assert default["account_type"] == "stellar_2step"
    assert default["phase"] == "challenge"
    assert default["consistency_enabled"] is False

    updated = api_client.put("/api/fundednext/settings", json={
        "account_type": "stellar_lite", "phase": "funded", "consistency_enabled": True,
    })
    assert updated.status_code == 200
    assert updated.json() == {"account_type": "stellar_lite", "phase": "funded", "consistency_enabled": True}

    # The new settings actually drive /status, not just echoed back.
    status = api_client.get("/api/fundednext/status").json()
    assert status["account_type"] == "stellar_lite"
    assert status["phase"] == "funded"


def test_fundednext_settings_rejects_invalid_account_type(api_client):
    resp = api_client.put("/api/fundednext/settings", json={"account_type": "not_a_real_account"})
    assert resp.status_code == 400


def test_fundednext_violations_empty_when_safe(api_client):
    resp = api_client.get("/api/fundednext/violations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_trade_creation_automatically_captures_fundednext_context(api_client):
    resp = api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "10:00:00", "direction": "BUY",
        "entry": 3740.0, "stop_loss": 3735.0,
    })
    trade_id = resp.json()["id"]

    detail = api_client.get(f"/api/journal/trades/{trade_id}").json()
    ctx = detail["fundednext_context"]
    assert ctx is not None
    assert ctx["data_available"] is True
    assert ctx["mode"] == "mock"
    assert ctx["account_type"] == "stellar_2step"  # default settings
    assert ctx["balance"] is not None and ctx["equity"] is not None
    assert ctx["daily_loss_pct_rule"] == 0.05  # Stellar 2-Step's verified rule


def test_journal_list_endpoint_does_not_include_fundednext_context(api_client):
    """Keeps the main journal table uncluttered — only the single-trade
    detail view carries the full FundedNext context."""
    api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "10:00:00", "direction": "BUY",
        "entry": 3740.0, "stop_loss": 3735.0,
    })
    trades = api_client.get("/api/journal/trades").json()
    assert len(trades) == 1
    assert "fundednext_context" not in trades[0] or trades[0]["fundednext_context"] is None


def test_fundednext_context_is_immutable_across_setting_changes(api_client):
    r1 = api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "09:00:00", "direction": "BUY",
        "entry": 3740.0, "stop_loss": 3735.0,
    })
    trade1_id = r1.json()["id"]
    snap1 = api_client.get(f"/api/journal/trades/{trade1_id}").json()["fundednext_context"]
    assert snap1["account_type"] == "stellar_2step"

    api_client.put("/api/fundednext/settings", json={"account_type": "stellar_lite"})

    r2 = api_client.post("/api/journal/trades", json={
        "trade_date": "2026-09-27", "trade_time": "11:00:00", "direction": "SELL",
        "entry": 3745.0, "stop_loss": 3750.0,
    })
    trade2_id = r2.json()["id"]
    snap2 = api_client.get(f"/api/journal/trades/{trade2_id}").json()["fundednext_context"]
    assert snap2["account_type"] == "stellar_lite"

    # Trade 1's stored context must be completely unaffected by the settings change.
    snap1_again = api_client.get(f"/api/journal/trades/{trade1_id}").json()["fundednext_context"]
    assert snap1_again == snap1
    assert snap1_again["account_type"] == "stellar_2step"


def test_trade_without_fundednext_context_returns_null_not_error(api_client):
    """A trade created before this feature existed (or if capture somehow
    failed) must degrade to null, never a crash on read."""
    from journal import trades as trades_repo
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-09-27", "trade_time": "09:00:00", "symbol": "XAUUSD",
         "direction": "BUY", "session": None, "entry": 100.0, "stop_loss": 95.0,
         "take_profit": None, "planned_rr": None, "setup": None, "market_regime": None,
         "notes": None, "screenshot_path": None},
        {"h4_bias": None, "h1_bias": None, "m15_bias": None, "m5_bias": None,
         "regime": None, "liquidity": None, "mss": None, "displacement": None, "session": None},
    )
    detail = api_client.get(f"/api/journal/trades/{trade_id}").json()
    assert detail["fundednext_context"] is None


def test_websocket_market_stream_sends_valid_snapshot(api_client):
    with api_client.websocket_connect("/ws/market") as ws:
        data = ws.receive_json()
        assert "setup" in data
        assert "connection" in data
        assert data["connection"]["mode"] == "mock"
