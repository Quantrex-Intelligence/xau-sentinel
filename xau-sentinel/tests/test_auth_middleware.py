"""DEP-001 (docs/validation/OPERATIONAL_ISSUES.md / deployment/DEPLOYMENT_ISSUES.md):
api/main.py::AuthMiddleware. Default-off design: with config.API_AUTH_TOKEN
blank (every test file's normal state, since nothing else in this project
sets it), the middleware is a complete no-op — proven here explicitly, not
just assumed, since every other test file's routes implicitly depend on
that staying true. When a token IS configured, every route and the
WebSocket require it except the exempt health/docs paths, and a rejection
still carries CORS headers (same reasoning as DEP-015)."""
import pytest
from fastapi.testclient import TestClient

import config
from api.main import app


@pytest.fixture
def api_client(temp_db):
    """Same pattern as tests/test_api.py's api_client fixture."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def token_required(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "s3cr3t-token")
    return "s3cr3t-token"


# ---------------------------------------------------------------------------
# Default (blank token): a complete no-op
# ---------------------------------------------------------------------------

def test_blank_token_means_no_auth_at_all(api_client):
    """The default state every other test file already relies on."""
    assert config.API_AUTH_TOKEN == ""
    resp = api_client.get("/api/health")
    assert resp.status_code == 200


def test_blank_token_websocket_connects_with_no_query_param(api_client):
    with api_client.websocket_connect("/ws/market") as ws:
        data = ws.receive_json()
        assert "connection" in data


# ---------------------------------------------------------------------------
# Token configured: enforced on ordinary routes
# ---------------------------------------------------------------------------

def test_missing_authorization_header_is_rejected(api_client, token_required):
    resp = api_client.get("/api/market/ticker")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Unauthorized"


def test_wrong_token_is_rejected(api_client, token_required):
    resp = api_client.get("/api/market/ticker", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_malformed_authorization_header_is_rejected(api_client, token_required):
    resp = api_client.get("/api/market/ticker", headers={"Authorization": token_required})  # missing "Bearer "
    assert resp.status_code == 401


def test_correct_bearer_token_is_accepted(api_client, token_required):
    resp = api_client.get("/api/market/ticker", headers={"Authorization": f"Bearer {token_required}"})
    assert resp.status_code == 200


def test_rejection_still_carries_cors_headers(api_client, token_required):
    """DEP-015's same reasoning: a browser must see a clean 401, not a
    CORS failure that hides the real reason."""
    resp = api_client.get("/api/market/ticker", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 401
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ---------------------------------------------------------------------------
# Exempt paths stay reachable even with a token configured
# ---------------------------------------------------------------------------

def test_health_stays_exempt(api_client, token_required):
    resp = api_client.get("/api/health")
    assert resp.status_code == 200


def test_docs_routes_stay_exempt(api_client, token_required):
    assert api_client.get("/openapi.json").status_code == 200
    assert api_client.get("/docs").status_code == 200


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

def test_websocket_without_token_is_rejected(api_client, token_required):
    with pytest.raises(Exception):
        with api_client.websocket_connect("/ws/market"):
            pass


def test_websocket_with_wrong_token_is_rejected(api_client, token_required):
    with pytest.raises(Exception):
        with api_client.websocket_connect("/ws/market?token=wrong-token"):
            pass


def test_websocket_with_correct_token_connects(api_client, token_required):
    with api_client.websocket_connect(f"/ws/market?token={token_required}") as ws:
        data = ws.receive_json()
        assert "connection" in data
