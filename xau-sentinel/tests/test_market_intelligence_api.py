"""API-level tests for GET /api/market-intelligence."""
import pytest
from fastapi.testclient import TestClient

import config
from api.main import app


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


def test_market_intelligence_endpoint_returns_the_full_structure(api_client):
    resp = api_client.get("/api/market-intelligence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_available"] is True
    assert "generated_at" in body
    assert body["macro"] is not None
    assert body["gold_fundamentals"] is not None
    assert body["cross_asset"] is not None
    assert len(body["events"]) > 0
    assert len(body["news"]) > 0
    assert "sources" in body


def test_market_intelligence_endpoint_never_claims_a_probability_or_win_forecast(api_client):
    body_text = api_client.get("/api/market-intelligence").text.lower()
    assert "probability" not in body_text
    assert "win_chance" not in body_text


def test_market_intelligence_news_articles_have_no_duplicate_headlines(api_client):
    body = api_client.get("/api/market-intelligence").json()
    headlines = [a["headline"] for a in body["news"]]
    assert len(headlines) == len(set(headlines))


def test_fred_api_key_never_appears_in_the_response_body(api_client, monkeypatch):
    secret = "sk-fred-secret-should-never-leak-anywhere"
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", secret)
    resp = api_client.get("/api/market-intelligence")
    assert secret not in resp.text
