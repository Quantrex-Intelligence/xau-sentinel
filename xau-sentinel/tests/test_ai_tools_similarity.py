"""Tests for ai/tools/similarity_tools.py — the find_similar_setups tool
wrapper. Read-only: never calls anything that writes to the journal."""
from journal import trades as trades_repo
from ai.tools import similarity_tools


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


def test_find_similar_setups_uses_the_live_setup_by_default(temp_db):
    result = similarity_tools.find_similar_setups({})
    assert result.data_available is True
    assert "query_features" in result.data


def test_find_similar_setups_unavailable_for_unknown_trade_id(temp_db):
    result = similarity_tools.find_similar_setups({"trade_id": 999999})
    assert result.data_available is False
    assert "999999" in result.reason


def test_find_similar_setups_by_trade_id_finds_other_historical_trades(temp_db):
    query_trade = trades_repo.create_trade(_trade_payload(), _context_payload())
    other_trade = trades_repo.create_trade(_trade_payload(), _context_payload())

    result = similarity_tools.find_similar_setups({"trade_id": query_trade, "min_similarity": 0.0})
    assert result.data_available is True
    trade_ids = {m["trade_id"] for m in result.data["matches"]}
    assert other_trade in trade_ids
    assert query_trade not in trade_ids  # never matches itself


def test_find_similar_setups_respects_top_k_argument(temp_db):
    for _ in range(4):
        trades_repo.create_trade(_trade_payload(), _context_payload())
    result = similarity_tools.find_similar_setups({"top_k": 1, "min_similarity": 0.0})
    assert len(result.data["matches"]) <= 1
