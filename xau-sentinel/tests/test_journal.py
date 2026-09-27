"""Journal lifecycle and analytics validation (spec sections 17-18)."""
from journal import trades as trades_repo


def _trade_payload(direction="BUY", entry=100.0, sl=95.0, tp=110.0):
    return {
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
        "direction": direction, "session": "London", "entry": entry, "stop_loss": sl,
        "take_profit": tp, "planned_rr": 2.0, "setup": "Sweep + MSS", "market_regime": "TRENDING UP",
        "notes": "test", "screenshot_path": None,
    }


def _context_payload():
    return {
        "h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
        "regime": "TRENDING UP", "liquidity": "Previous Day Low swept", "mss": "Bullish",
        "displacement": "Bullish", "session": "London",
    }


def test_full_trade_lifecycle_create_capture_close(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    assert trade_id is not None

    trade = trades_repo.get_trade(trade_id)
    assert trade["status"] == "OPEN"
    assert trade["h4_bias"] == "BULLISH"  # context captured automatically, joined in
    assert trade["mss"] == "Bullish"

    trades_repo.close_trade(trade_id, {
        "exit_price": 110.0, "result": "WIN", "pnl": 500.0, "r_multiple": 2.0,
        "duration_minutes": 45, "exit_reason": "Hit TP", "rule_followed": "Yes",
        "mistake": None, "exit_notes": "clean",
    })

    closed = trades_repo.get_trade(trade_id)
    assert closed["status"] == "CLOSED"
    assert closed["result"] == "WIN"
    assert closed["r_multiple"] == 2.0


def test_manual_fields_are_preserved_alongside_automatic_context(temp_db):
    """The trader can enter what the system cannot know (notes, setup label)
    without it being overwritten by the automatic context capture."""
    payload = _trade_payload()
    payload["notes"] = "Took this because of NY session liquidity grab"
    trade_id = trades_repo.create_trade(payload, _context_payload())
    trade = trades_repo.get_trade(trade_id)
    assert trade["notes"] == "Took this because of NY session liquidity grab"
    assert trade["setup"] == "Sweep + MSS"


def test_analytics_known_dataset_5_wins_4_losses_1_be(temp_db):
    """5 wins (avg +2R), 4 losses (avg -1R), 1 break-even (0R):
    total_r = 5*2 + 4*(-1) + 0 = 6, win_rate = 5/10 = 50%,
    profit_factor = gross_win(10) / gross_loss(4) = 2.5."""
    results = ["WIN"] * 5 + ["LOSS"] * 4 + ["BE"]
    r_values = [2.0] * 5 + [-1.0] * 4 + [0.0]

    for i, (result, r) in enumerate(zip(results, r_values)):
        trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
        trades_repo.close_trade(trade_id, {
            "exit_price": 105.0, "result": result, "pnl": r * 100, "r_multiple": r,
            "duration_minutes": 30, "exit_reason": "test", "rule_followed": "Yes",
            "mistake": None, "exit_notes": None,
        })

    df = trades_repo.list_trades()
    stats = trades_repo.compute_analytics(df)

    assert stats["total_trades"] == 10
    assert stats["wins"] == 5
    assert stats["losses"] == 4
    assert stats["breakeven"] == 1
    assert stats["win_rate"] == 50.0
    assert stats["total_r"] == 6.0
    assert stats["avg_r"] == 0.6
    assert stats["profit_factor"] == 2.5


def test_analytics_empty_dataset_does_not_divide_by_zero(temp_db):
    df = trades_repo.list_trades()
    stats = trades_repo.compute_analytics(df)
    assert stats["total_trades"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["profit_factor"] is None


def test_analytics_all_losses_profit_factor_is_zero(temp_db):
    """Zero gross win with nonzero gross loss is a legitimate profit factor
    of 0.0 (worst possible), not an error condition."""
    for _ in range(3):
        trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
        trades_repo.close_trade(trade_id, {
            "exit_price": 95.0, "result": "LOSS", "pnl": -100.0, "r_multiple": -1.0,
            "duration_minutes": 30, "exit_reason": "SL hit", "rule_followed": "Yes",
            "mistake": "n/a", "exit_notes": None,
        })
    df = trades_repo.list_trades()
    stats = trades_repo.compute_analytics(df)
    assert stats["profit_factor"] == 0.0
    assert stats["total_r"] == -3.0


def test_analytics_all_wins_profit_factor_is_none_not_infinite(temp_db):
    """Zero gross loss with nonzero gross win must report None (undefined),
    never a raw division by zero / inf leaking into the UI."""
    for _ in range(3):
        trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
        trades_repo.close_trade(trade_id, {
            "exit_price": 110.0, "result": "WIN", "pnl": 200.0, "r_multiple": 2.0,
            "duration_minutes": 30, "exit_reason": "Hit TP", "rule_followed": "Yes",
            "mistake": None, "exit_notes": None,
        })
    df = trades_repo.list_trades()
    stats = trades_repo.compute_analytics(df)
    assert stats["profit_factor"] is None
    assert stats["total_r"] == 6.0


def test_open_trades_excluded_from_analytics(temp_db):
    trades_repo.create_trade(_trade_payload(), _context_payload())  # left OPEN
    df = trades_repo.list_trades()
    stats = trades_repo.compute_analytics(df)
    assert stats["total_trades"] == 0


def test_today_r_total_sums_only_closed_trades_for_the_given_day(temp_db):
    """Regression test for BUG-3 (see final report): the Risk panel's
    "Today P/L" was hardcoded to 0.0 and never wired to real trade data."""
    t1 = trades_repo.create_trade(_trade_payload(), _context_payload())
    trades_repo.close_trade(t1, {
        "exit_price": 110.0, "result": "WIN", "pnl": 500.0, "r_multiple": 2.0,
        "duration_minutes": 45, "exit_reason": "Hit TP", "rule_followed": "Yes",
        "mistake": None, "exit_notes": None,
    })

    t2 = trades_repo.create_trade(_trade_payload(), _context_payload())
    trades_repo.close_trade(t2, {
        "exit_price": 95.0, "result": "LOSS", "pnl": -100.0, "r_multiple": -1.0,
        "duration_minutes": 20, "exit_reason": "SL hit", "rule_followed": "Yes",
        "mistake": None, "exit_notes": None,
    })

    # Left OPEN — must not count toward today's realized P/L.
    trades_repo.create_trade(_trade_payload(), _context_payload())

    # A different day's closed trade — must not be included either.
    other_day = trades_repo.create_trade({**_trade_payload(), "trade_date": "2020-01-01"}, _context_payload())
    trades_repo.close_trade(other_day, {
        "exit_price": 130.0, "result": "WIN", "pnl": 1000.0, "r_multiple": 5.0,
        "duration_minutes": 10, "exit_reason": "Hit TP", "rule_followed": "Yes",
        "mistake": None, "exit_notes": None,
    })

    assert trades_repo.today_r_total("2026-01-05") == 1.0  # 2.0 + (-1.0)


def test_filters_narrow_the_trade_list(temp_db):
    trades_repo.create_trade(_trade_payload(direction="BUY"), _context_payload())
    trades_repo.create_trade(_trade_payload(direction="SELL"), _context_payload())

    buys = trades_repo.list_trades({"direction": "BUY"})
    assert len(buys) == 1
    assert buys.iloc[0]["direction"] == "BUY"
