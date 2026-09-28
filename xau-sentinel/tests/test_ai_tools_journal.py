"""Tests for ai/tools/journal_tools.py — including search_journal, the one
genuinely new query surface this stage adds, implemented entirely as a
read-only filter in the tool layer (journal/trades.py itself is untouched)."""
from journal import trades as trades_repo
from ai.tools import journal_tools


def _trade_payload(**overrides):
    payload = {
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
        "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
        "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep + MSS", "market_regime": "TRENDING UP",
        "notes": "Waited for London liquidity sweep before entering", "screenshot_path": None,
    }
    payload.update(overrides)
    return payload


def _context_payload():
    return {
        "h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
        "regime": "TRENDING UP", "liquidity": "Previous Day Low swept", "mss": "Bullish",
        "displacement": "Bullish", "session": "London",
    }


def test_get_trade_returns_data_for_an_existing_trade(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    result = journal_tools.get_trade({"trade_id": trade_id})
    assert result.data_available is True
    assert result.data["trade"]["id"] == trade_id


def test_get_trade_unavailable_for_unknown_id(temp_db):
    result = journal_tools.get_trade({"trade_id": 999999})
    assert result.data_available is False
    assert "999999" in result.reason


def test_get_trade_history_empty_journal(temp_db):
    result = journal_tools.get_trade_history({})
    assert result.data_available is False


def test_get_trade_history_returns_recent_trades(temp_db):
    trades_repo.create_trade(_trade_payload(), _context_payload())
    trades_repo.create_trade(_trade_payload(trade_date="2026-01-06"), _context_payload())
    result = journal_tools.get_trade_history({"limit": 1})
    assert result.data_available is True
    assert len(result.data["trades"]) == 1


def test_get_performance_computes_analytics(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    trades_repo.close_trade(trade_id, {
        "exit_price": 110.0, "result": "WIN", "pnl": 500.0, "r_multiple": 2.0,
        "duration_minutes": 45, "exit_reason": "Hit TP", "rule_followed": "Yes",
        "mistake": None, "exit_notes": "clean",
    })
    result = journal_tools.get_performance({})
    assert result.data_available is True
    assert result.data["total_trades"] == 1
    assert result.data["wins"] == 1


def test_search_journal_finds_a_matching_trade_by_notes(temp_db):
    trades_repo.create_trade(_trade_payload(notes="Took this because of a liquidity sweep at NY open"),
                              _context_payload())
    trades_repo.create_trade(_trade_payload(notes="Unrelated entry, no special reason"), _context_payload())

    result = journal_tools.search_journal({"query": "liquidity sweep"})
    assert result.data_available is True
    assert result.data["matched"] == 1


def test_search_journal_requires_a_query(temp_db):
    result = journal_tools.search_journal({"query": ""})
    assert result.data_available is False


def test_search_journal_no_matches_is_still_data_available_true(temp_db):
    trades_repo.create_trade(_trade_payload(), _context_payload())
    result = journal_tools.search_journal({"query": "nonexistent keyword xyz"})
    assert result.data_available is True
    assert result.data["matched"] == 0
