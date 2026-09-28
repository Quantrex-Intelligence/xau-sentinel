"""Tests for ai/similarity/engine.py: top-K, threshold, insufficient-data
exclusion + count, self-match exclusion, outcome attached after scoring and
separated by status, and duplicate/identical-feature trades both returned
distinctly (never merged or deduplicated away)."""
from journal import trades as trades_repo
from ai.similarity import engine
from ai.similarity.models import SetupFeatures


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


def _query() -> SetupFeatures:
    return SetupFeatures(
        direction="BUY", h4_structure="BULLISH", h1_structure="BULLISH",
        m15_structure="PULLBACK", m5_structure="BULLISH", regime="TRENDING UP",
        liquidity_kind="sweep_low", mss_direction="bullish", displacement="bullish",
        session="London", planned_rr=2.5,
    )


def test_find_similar_setups_empty_journal_returns_no_matches(temp_db):
    result = engine.find_similar_setups(_query())
    assert result.matches == []
    assert result.considered_count == 0
    assert result.excluded_count == 0


def test_find_similar_setups_finds_an_identical_historical_trade(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    result = engine.find_similar_setups(_query(), min_similarity=0.0)
    assert len(result.matches) == 1
    assert result.matches[0].trade_id == trade_id
    assert result.matches[0].similarity == 1.0


def test_insufficient_data_trades_are_excluded_and_counted(temp_db):
    trades_repo.create_trade(_trade_payload(), _context_payload(h1_bias=None))  # missing required field
    trades_repo.create_trade(_trade_payload(), _context_payload())              # sufficient
    result = engine.find_similar_setups(_query(), min_similarity=0.0)
    assert result.excluded_count == 1
    assert result.considered_count == 1


def test_min_similarity_threshold_filters_out_dissimilar_trades(temp_db):
    trades_repo.create_trade(_trade_payload(direction="SELL"), _context_payload(
        h4_bias="BEARISH", h1_bias="BEARISH", m15_bias="RANGING", m5_bias="BEARISH",
        regime="TRENDING DOWN", liquidity="Asian High swept", mss="Bearish",
        displacement="Bearish", session="New York",
    ))
    result = engine.find_similar_setups(_query(), min_similarity=0.9)
    assert result.matches == []
    # Still considered (had enough data), just scored below threshold.
    assert result.considered_count == 1


def test_top_k_limits_the_number_of_matches_returned(temp_db):
    for _ in range(5):
        trades_repo.create_trade(_trade_payload(), _context_payload())
    result = engine.find_similar_setups(_query(), top_k=2, min_similarity=0.0)
    assert len(result.matches) == 2


def test_matches_are_sorted_by_similarity_descending(temp_db):
    trades_repo.create_trade(_trade_payload(), _context_payload())  # perfect match
    trades_repo.create_trade(_trade_payload(), _context_payload(session="New York"))  # slightly off
    result = engine.find_similar_setups(_query(), min_similarity=0.0)
    similarities = [m.similarity for m in result.matches]
    assert similarities == sorted(similarities, reverse=True)


def test_exclude_trade_id_prevents_a_trade_from_matching_itself(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    result = engine.find_similar_setups(_query(), exclude_trade_id=trade_id, min_similarity=0.0)
    assert all(m.trade_id != trade_id for m in result.matches)


def test_duplicate_identical_trades_are_each_returned_distinctly(temp_db):
    id_a = trades_repo.create_trade(_trade_payload(), _context_payload())
    id_b = trades_repo.create_trade(_trade_payload(), _context_payload())
    result = engine.find_similar_setups(_query(), min_similarity=0.0)
    trade_ids = {m.trade_id for m in result.matches}
    assert {id_a, id_b} <= trade_ids
    assert len(result.matches) == len({m.trade_id for m in result.matches})  # no accidental merging


def test_outcome_is_unknown_for_an_open_trade(temp_db):
    trades_repo.create_trade(_trade_payload(), _context_payload())
    result = engine.find_similar_setups(_query(), min_similarity=0.0)
    assert result.matches[0].outcome.status == "OPEN"
    assert result.matches[0].outcome.result is None


def test_outcome_reflects_a_closed_trades_result_separately_from_scoring(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    trades_repo.close_trade(trade_id, {
        "exit_price": 110.0, "result": "WIN", "pnl": 500.0, "r_multiple": 2.0,
        "duration_minutes": 45, "exit_reason": "Hit TP", "rule_followed": "Yes",
        "mistake": None, "exit_notes": "clean",
    })
    result = engine.find_similar_setups(_query(), min_similarity=0.0)
    match = result.matches[0]
    assert match.outcome.status == "CLOSED"
    assert match.outcome.result == "WIN"
    assert match.outcome.r_multiple == 2.0
    # Closing the trade must not have changed its similarity score at all.
    assert match.similarity == 1.0


def test_resolve_query_features_by_trade_id(temp_db):
    trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
    features, exclude_id = engine.resolve_query_features(trade_id)
    assert features.direction == "BUY"
    assert exclude_id == trade_id


def test_resolve_query_features_unknown_trade_id_returns_none(temp_db):
    features, exclude_id = engine.resolve_query_features(999999)
    assert features is None
    assert exclude_id is None


def test_resolve_query_features_none_uses_the_live_setup(temp_db):
    features, exclude_id = engine.resolve_query_features(None)
    assert exclude_id is None
    assert features is not None  # mock mode always has live setup data available
