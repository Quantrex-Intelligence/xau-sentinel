"""Stage 23D (Lane D) journal hardening: VAL-024 (no re-close of a closed
trade), VAL-029 (trade + FundedNext snapshot are atomic), VAL-030 (one
snapshot per trade, enforced even on a legacy DB), VAL-032 (result is
validated/normalized to WIN/LOSS/BE). Every test drives the real code path
(temp_db + real create_trade/close_trade or the real API route)."""
import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from api.routes import journal as journal_routes
from journal import trades as trades_repo
from journal.database import get_connection
from risk.fundednext_journal import get_snapshot, save_snapshot
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel


def _trade_payload():
    return {
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
        "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
        "take_profit": 110.0, "planned_rr": 2.0, "setup": None, "market_regime": None,
        "notes": None, "screenshot_path": None,
    }


def _context_payload():
    return {"h4_bias": "BULLISH", "h1_bias": None, "m15_bias": None, "m5_bias": None, "regime": None,
            "liquidity": None, "mss": None, "displacement": None, "session": "London"}


def _status(balance=50_000.0) -> FundedNextStatus:
    return FundedNextStatus(
        account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock", data_available=True,
        balance=balance, equity=balance, today_pnl=0.0, daily_loss_remaining=2_500.0,
        daily_loss_used_pct=0.0, max_drawdown_remaining=5_000.0, max_drawdown_used_pct=0.0,
        safety_level=SafetyLevel.SAFE, reason="ok",
    )


def _count(table: str) -> int:
    with get_connection() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()[0]


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


def _post_trade(api_client):
    resp = api_client.post("/api/journal/trades", json={
        "direction": "BUY", "entry": 3740.0, "stop_loss": 3735.0, "take_profit": 3750.0,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# VAL-024: a closed trade can't be closed again
# ---------------------------------------------------------------------------

def test_repo_close_trade_does_not_overwrite_an_already_closed_trade(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    assert trades_repo.close_trade(trade_id, {"exit_price": 110.0, "result": "WIN", "pnl": 200.0,
                                              "r_multiple": 2.0}) is True
    assert trades_repo.close_trade(trade_id, {"exit_price": 95.0, "result": "LOSS"}) is False

    trade = trades_repo.get_trade(trade_id)
    assert (trade["result"], trade["pnl"], trade["r_multiple"], trade["exit_price"]) == ("WIN", 200.0, 2.0, 110.0)


def test_api_second_close_is_rejected_with_409_and_changes_nothing(api_client):
    trade_id = _post_trade(api_client)["id"]
    first = api_client.patch(f"/api/journal/trades/{trade_id}/close",
                             json={"exit_price": 3750.0, "result": "WIN", "pnl": 500.0, "r_multiple": 2.0})
    assert first.status_code == 200

    second = api_client.patch(f"/api/journal/trades/{trade_id}/close",
                              json={"exit_price": 3735.0, "result": "LOSS"})
    assert second.status_code == 409

    trade = trades_repo.get_trade(trade_id)
    assert (trade["result"], trade["pnl"], trade["r_multiple"]) == ("WIN", 500.0, 2.0)


def test_api_close_of_missing_trade_is_still_404(api_client):
    resp = api_client.patch("/api/journal/trades/9999/close", json={"exit_price": 1.0, "result": "WIN"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# VAL-029: trade and its FundedNext snapshot are written atomically
# ---------------------------------------------------------------------------

def test_api_create_trade_saves_trade_and_snapshot_together(api_client):
    trade_id = _post_trade(api_client)["id"]
    assert get_snapshot(trade_id) is not None
    assert _count("trades") == 1 and _count("fundednext_context") == 1


def test_api_status_failure_creates_no_trade(api_client, monkeypatch):
    """compute_status() may hit MT5; if it fails no orphan trade may remain."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("MT5 unavailable")
    monkeypatch.setattr(journal_routes, "compute_status", boom)

    resp = api_client.post("/api/journal/trades", json={"direction": "BUY", "entry": 3740.0, "stop_loss": 3735.0})
    assert resp.status_code == 500
    assert "Nothing was written" in resp.json()["detail"]
    assert _count("trades") == 0
    assert _count("journal_context") == 0
    assert _count("fundednext_context") == 0


def test_api_snapshot_write_failure_rolls_back_the_trade_insert(api_client, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(journal_routes, "save_fundednext_snapshot", boom)

    resp = api_client.post("/api/journal/trades", json={"direction": "BUY", "entry": 3740.0, "stop_loss": 3735.0})
    assert resp.status_code == 500
    assert _count("trades") == 0
    assert _count("journal_context") == 0


# ---------------------------------------------------------------------------
# VAL-030: one snapshot per trade, structurally
# ---------------------------------------------------------------------------

def test_second_snapshot_for_same_trade_is_rejected(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    save_snapshot(trade_id, _status(50_000.0), 0.05, 0.10)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        save_snapshot(trade_id, _status(99_999.0), 0.05, 0.10)
    assert get_snapshot(trade_id)["balance"] == 50_000.0


# DEP-002: test_init_table_dedupes_a_legacy_db_keeping_the_earliest_snapshot
# and test_init_table_is_idempotent are gone -- they covered the
# sqlite3-era CREATE TABLE IF NOT EXISTS + inline DELETE-dedup migration
# that init_table() used to run, needed only because that pattern could
# never alter a live table. Alembic (see alembic/versions/0001_initial_schema.py)
# creates the already-deduplicated, indexed shape directly; there is no
# legacy-DB dedup path left to test.


# ---------------------------------------------------------------------------
# VAL-032: result validated and normalized
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sent,stored", [("win", "WIN"), (" Loss ", "LOSS"), ("be", "BE"), ("WIN", "WIN")])
def test_api_close_normalizes_result_case(api_client, sent, stored):
    trade_id = _post_trade(api_client)["id"]
    resp = api_client.patch(f"/api/journal/trades/{trade_id}/close", json={"exit_price": 3750.0, "result": sent})
    assert resp.status_code == 200, resp.text
    assert trades_repo.get_trade(trade_id)["result"] == stored


@pytest.mark.parametrize("bad", ["WON", "", "breakeven", 1])
def test_api_close_rejects_unknown_result_and_leaves_trade_open(api_client, bad):
    trade_id = _post_trade(api_client)["id"]
    resp = api_client.patch(f"/api/journal/trades/{trade_id}/close", json={"exit_price": 3750.0, "result": bad})
    assert resp.status_code == 422
    assert trades_repo.get_trade(trade_id)["status"] == "OPEN"


def test_analytics_counts_legacy_lowercase_results(temp_db):
    """Rows stored before validation existed (written straight through the
    repo, bypassing the API schema) must still be counted."""
    for result, r in [("win", 2.0), (" Loss", -1.0), ("be", 0.0), ("WIN", 1.0)]:
        trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
        trades_repo.close_trade(trade_id, {"exit_price": 100.0, "result": result, "r_multiple": r})

    stats = trades_repo.compute_analytics(trades_repo.list_trades())
    assert (stats["total_trades"], stats["wins"], stats["losses"], stats["breakeven"]) == (4, 2, 1, 1)
    assert stats["win_rate"] == 50.0
    assert stats["profit_factor"] == 3.0
