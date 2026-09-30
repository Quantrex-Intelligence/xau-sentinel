"""API-level tests for /api/trade-review/{...} — thin pass-throughs;
GET never calls the LLM (structural); immutability: a before/after
snapshot of trades/journal_context/fundednext_context proves review
generation never writes to any of them."""
import inspect

import pytest
from fastapi.testclient import TestClient

import ai.trade_review.service as service_mod
from ai.trade_review import store
from ai.providers.base import BaseProvider, ProviderResponse
from api.main import app


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def chat(self, system, messages, tools=None):
        return ProviderResponse(text="The trade followed the recorded H1 bias and MSS confirmation.",
                                 provider=self.name, model=self.model)


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def closed_trade_id(api_client):
    from journal import trades as trades_repo
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-01", "trade_time": "10:00", "symbol": "XAUUSD", "direction": "BUY",
         "entry": 3700.0, "stop_loss": 3690.0, "take_profit": 3730.0, "planned_rr": 3.0},
        {"h1_bias": "BULLISH", "liquidity": "Previous Day Low swept", "mss": "Bullish", "displacement": "Bullish"},
    )
    trades_repo.close_trade(trade_id, {"exit_price": 3730.0, "result": "WIN", "pnl": 300.0,
                                        "r_multiple": 3.0, "duration_minutes": 45})
    return trade_id


@pytest.fixture(autouse=True)
def _stub_provider_and_evidence(monkeypatch):
    monkeypatch.setattr(service_mod, "get_provider", lambda: _RecordingProvider())
    from ai.trade_review import context as ctx
    monkeypatch.setattr(ctx.similarity_engine, "resolve_query_features", lambda trade_id=None: (None, None))
    monkeypatch.setattr(ctx.knowledge_retrieval, "retrieve", lambda q: [])
    monkeypatch.setattr(ctx.memory_retrieval, "retrieve_memory", lambda q: [])


def test_get_trade_review_returns_200_without_interpretation(api_client, closed_trade_id):
    resp = api_client.get(f"/api/trade-review/{closed_trade_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_id"] == closed_trade_id
    assert body["outcome"] == "WIN"
    assert body["strategy_alignment"] == "ALIGNED"
    assert body["interpretation"] is None


def test_get_trade_review_404s_for_unknown_id(api_client):
    resp = api_client.get("/api/trade-review/999999")
    assert resp.status_code == 404


def test_generate_trade_review_populates_interpretation(api_client, closed_trade_id):
    resp = api_client.post(f"/api/trade-review/{closed_trade_id}/generate")
    assert resp.status_code == 200
    assert resp.json()["interpretation"] is not None


def test_get_after_generate_returns_the_cached_interpretation(api_client, closed_trade_id):
    api_client.post(f"/api/trade-review/{closed_trade_id}/generate")
    resp = api_client.get(f"/api/trade-review/{closed_trade_id}")
    assert resp.json()["interpretation"] is not None


def test_summary_endpoint_returns_expected_shape(api_client, closed_trade_id):
    resp = api_client.get("/api/trade-review/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trades_reviewed"] >= 1
    assert "patterns" in body


def test_patterns_endpoint_returns_a_list(api_client, closed_trade_id):
    resp = api_client.get("/api/trade-review/patterns")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_route_never_calls_the_llm_structurally():
    import api.routes.trade_review as route_mod
    source = inspect.getsource(route_mod.get_trade_review)
    assert "generate" not in source.lower()


# ---------------------------------------------------------------------------
# Immutability — review generation never writes to trades/journal_context/
# fundednext_context.
# ---------------------------------------------------------------------------

def test_generating_a_review_never_modifies_the_underlying_trade(api_client, closed_trade_id):
    from sqlalchemy import text
    from journal.database import get_connection

    def _snapshot_rows():
        with get_connection() as conn:
            trade = dict(conn.execute(
                text("SELECT * FROM trades WHERE id = :id"), {"id": closed_trade_id}
            ).mappings().fetchone())
            context = conn.execute(
                text("SELECT * FROM journal_context WHERE trade_id = :id"), {"id": closed_trade_id}
            ).mappings().fetchone()
            fn = conn.execute(
                text("SELECT * FROM fundednext_context WHERE trade_id = :id"), {"id": closed_trade_id}
            ).mappings().fetchone()
            return trade, dict(context) if context else None, dict(fn) if fn else None

    before = _snapshot_rows()
    api_client.post(f"/api/trade-review/{closed_trade_id}/generate")
    after = _snapshot_rows()

    assert before == after


def test_trade_review_routes_never_write_to_trades_or_journal_context():
    import api.routes.trade_review as route_mod
    source = inspect.getsource(route_mod)
    for banned in ("close_trade", "create_trade", "UPDATE trades", "UPDATE journal_context", "save_fundednext_snapshot"):
        assert banned not in source
