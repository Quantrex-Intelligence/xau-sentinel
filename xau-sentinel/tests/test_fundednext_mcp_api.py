"""API-level tests for GET /api/fundednext/mcp/*. All FundedNext MCP calls
are mocked at risk.fundednext_mcp._call_tool_uncached — no real network
call. Also guards that this integration never touches the existing,
MT5-derived /api/fundednext/* routes (api/routes/fundednext.py)."""
import pytest
from fastapi.testclient import TestClient

import config
from ai.market_intelligence.providers import cache
from api.main import app
from risk import fundednext_mcp


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _clear_mcp_cache():
    cache.clear()
    yield
    cache.clear()


def test_config_reports_not_configured_when_token_is_blank(api_client, monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", "")
    resp = api_client.get("/api/fundednext/mcp/config")
    assert resp.status_code == 200
    assert resp.json() == {"configured": False}


def test_config_reports_configured_when_token_is_set(api_client, monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", "a-real-token")
    resp = api_client.get("/api/fundednext/mcp/config")
    assert resp.json() == {"configured": True}


def test_accounts_endpoint_returns_data_available_false_when_unconfigured(api_client, monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", "")
    resp = api_client.get("/api/fundednext/mcp/accounts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_available"] is False
    assert body["raw"] is None


def test_accounts_endpoint_returns_the_mocked_payload(api_client, monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", "test-token")

    async def _fake(name, arguments):
        return {"data": [{"id": 1, "login": "12345", "status": "active"}]}

    monkeypatch.setattr(fundednext_mcp, "_call_tool_uncached", _fake)

    resp = api_client.get("/api/fundednext/mcp/accounts?tab=forex")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_available"] is True
    assert body["raw"]["data"][0]["login"] == "12345"


def test_account_scoped_routes_pass_the_account_id_through(api_client, monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", "test-token")

    async def _fake(name, arguments):
        return {"tool": name, "account_id": arguments.get("account_id")}

    monkeypatch.setattr(fundednext_mcp, "_call_tool_uncached", _fake)

    resp = api_client.get("/api/fundednext/mcp/accounts/acct-42/risk-card")
    body = resp.json()
    assert body["raw"] == {"tool": "get_risk_card", "account_id": "acct-42"}


def test_a_real_token_never_appears_in_any_mcp_response_body(api_client, monkeypatch):
    secret = "67165153-should-never-leak-anywhere"
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", secret)

    async def _fake(name, arguments):
        return {"ok": True}

    monkeypatch.setattr(fundednext_mcp, "_call_tool_uncached", _fake)

    for path in ("/api/fundednext/mcp/config", "/api/fundednext/mcp/accounts", "/api/fundednext/mcp/payout-history"):
        resp = api_client.get(path)
        assert secret not in resp.text


def test_a_real_token_never_appears_in_logs_during_a_normal_request(api_client, monkeypatch, caplog):
    secret = "67165153-should-never-leak-into-logs"
    monkeypatch.setattr(config, "FUNDEDNEXT_MCP_TOKEN", secret)

    async def _fake(name, arguments):
        return {"ok": True}

    monkeypatch.setattr(fundednext_mcp, "_call_tool_uncached", _fake)

    with caplog.at_level("DEBUG"):
        api_client.get("/api/fundednext/mcp/accounts")

    for record in caplog.records:
        assert secret not in record.getMessage()


def test_existing_mt5_derived_fundednext_status_route_is_unaffected(api_client):
    """Regression guard: this integration must never touch
    risk/fundednext.py or api/routes/fundednext.py."""
    resp = api_client.get("/api/fundednext/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "mock"  # still MT5/mock-derived, untouched


