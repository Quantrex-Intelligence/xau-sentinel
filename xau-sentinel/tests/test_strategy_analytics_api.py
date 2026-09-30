"""API-level tests for /api/strategy-analytics/{...} — thin pass-throughs;
every response is computed fresh, nothing is written. Immutability: a
before/after snapshot of trades/journal_context/fundednext_context/
monitoring_alerts/memory_records proves both GET endpoints never write to
any of them.
"""
import inspect

import pytest
from fastapi.testclient import TestClient

from api.main import app


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


def test_get_strategy_analytics_returns_expected_shape(api_client, closed_trade_id):
    resp = api_client.get("/api/strategy-analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overview"]["total_trades"] >= 1
    assert body["overview"]["strategy_alignment_counts"]["ALIGNED"] >= 1
    assert isinstance(body["adherence"], list)


def test_get_dimension_breakdown_returns_expected_shape(api_client, closed_trade_id):
    resp = api_client.get("/api/strategy-analytics/dimensions/direction")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dimension"] == "direction"
    assert any(row["value"] == "BUY" for row in body["rows"])


def test_get_dimension_breakdown_400s_for_unknown_dimension(api_client):
    resp = api_client.get("/api/strategy-analytics/dimensions/not_a_real_dimension")
    assert resp.status_code == 400


def test_strategy_analytics_routes_never_write_anything_structurally():
    import api.routes.strategy_analytics as route_mod
    source = inspect.getsource(route_mod)
    for banned in ("close_trade", "create_trade", "UPDATE ", "INSERT ", "save_fundednext_snapshot", "conn.commit"):
        assert banned not in source


# ---------------------------------------------------------------------------
# Immutability — hitting either endpoint never writes to any source table.
# ---------------------------------------------------------------------------

def test_hitting_both_endpoints_never_modifies_source_tables(api_client, closed_trade_id):
    from sqlalchemy import text
    from journal.database import get_connection

    def _snapshot():
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
            alerts = conn.execute(text("SELECT * FROM monitoring_alerts")).mappings().fetchall()
            memories = conn.execute(text("SELECT * FROM memory_records")).mappings().fetchall()
            return (
                trade, dict(context) if context else None, dict(fn) if fn else None,
                [dict(r) for r in alerts], [dict(r) for r in memories],
            )

    before = _snapshot()
    api_client.get("/api/strategy-analytics")
    api_client.get("/api/strategy-analytics/dimensions/direction")
    after = _snapshot()

    assert before == after
