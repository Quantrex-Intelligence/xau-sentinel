"""API-level tests for /api/explanations/{alert,trade}/{id} — thin
pass-throughs over ai.explanations.service."""
import inspect

import pytest
from fastapi.testclient import TestClient

import ai.explanations.service as service_mod
from ai.explanations import store
from ai.monitoring import store as monitoring_store
from ai.monitoring.models import AlertEvent, AlertType, Severity
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderResponse
from api.main import app


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def chat(self, system, messages, tools=None):
        return ProviderResponse(text="A liquidity sweep and MSS confirmed the bullish setup.",
                                 provider=self.name, model=self.model)


@pytest.fixture
def api_client(temp_db):
    monitoring_store.init_table()
    store.init_table()
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _stub_provider_and_evidence(monkeypatch):
    monkeypatch.setattr(service_mod, "get_provider", lambda: _RecordingProvider())
    from ai.explanations import context as ctx
    monkeypatch.setattr(ctx.mi_context, "build_market_intelligence_context", lambda: None)
    monkeypatch.setattr(ctx.similarity_engine, "resolve_query_features", lambda trade_id=None: (None, None))
    monkeypatch.setattr(ctx.knowledge_retrieval, "retrieve", lambda q: [])
    monkeypatch.setattr(ctx.memory_retrieval, "retrieve_memory", lambda q: [])


def _seed_alert():
    return monitoring_store.create_alert(AlertEvent(
        type=AlertType.APLUS_SETUP_DETECTED, severity=Severity.INFO, title="A+ setup detected — BUY",
        message="BUY A+ setup confirmed.", dedup_key="k1",
        payload={"direction": "BUY", "entry": 3700.0, "stop_loss": 3690.0, "target": 3730.0, "rr": 3.0},
    ))


def test_get_alert_explanation_returns_200_with_expected_shape(api_client):
    alert = _seed_alert()
    resp = api_client.get(f"/api/explanations/alert/{alert.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject_type"] == "alert"
    assert body["subject_id"] == alert.id
    assert "interpretation" in body
    assert "deterministic_facts" in body


def test_get_alert_explanation_404s_for_unknown_id(api_client):
    resp = api_client.get("/api/explanations/alert/99999")
    assert resp.status_code == 404


def test_generate_alert_explanation_overwrites_cache(api_client):
    alert = _seed_alert()
    first = api_client.get(f"/api/explanations/alert/{alert.id}").json()
    second = api_client.post(f"/api/explanations/alert/{alert.id}/generate").json()
    assert first["generated_at"] <= second["generated_at"]


def test_get_trade_explanation_404s_for_unknown_id(api_client):
    resp = api_client.get("/api/explanations/trade/99999")
    assert resp.status_code == 404


def test_get_trade_explanation_returns_200_for_a_real_trade(api_client):
    from journal import trades as trades_repo
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-01", "trade_time": "10:00", "symbol": "XAUUSD", "direction": "BUY",
         "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0},
        {"h1_bias": "BULLISH"},
    )
    resp = api_client.get(f"/api/explanations/trade/{trade_id}")
    assert resp.status_code == 200
    assert resp.json()["subject_type"] == "trade"


def test_explanation_degrades_gracefully_when_provider_unavailable(api_client, monkeypatch):
    def raise_config():
        raise ProviderConfigError("not configured")
    monkeypatch.setattr(service_mod, "get_provider", raise_config)

    alert = _seed_alert()
    resp = api_client.get(f"/api/explanations/alert/{alert.id}")
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["interpretation"].lower()


def test_malformed_model_response_is_handled_without_a_500(api_client, monkeypatch):
    class _EmptyReplyProvider(BaseProvider):
        name = "fake"
        model = "fake-model"

        def chat(self, system, messages, tools=None):
            return ProviderResponse(text="", provider=self.name, model=self.model)

    monkeypatch.setattr(service_mod, "get_provider", lambda: _EmptyReplyProvider())
    alert = _seed_alert()
    resp = api_client.get(f"/api/explanations/alert/{alert.id}")
    assert resp.status_code == 200  # an empty reply is still a valid (if unhelpful) interpretation string


def test_explanations_routes_never_call_the_deterministic_evaluator():
    import api.routes.explanations as explanations_route
    source = inspect.getsource(explanations_route)
    for banned in ("evaluate_deterministic", "evaluate_current_setup", "trades_repo", "create_trade"):
        assert banned not in source
