"""DEP-014 regression: the similarity feature path must treat NaN (what
pd.read_sql_query yields for a NULL column under pandas 3, and for any NULL
in a float column under pandas 2) exactly like None — never crash on
`.lower()` and never let NaN slip past an `is None` check."""
import numpy as np
import pandas as pd
import pytest

from ai.similarity import engine
from ai.similarity.features import _infer_liquidity_kind, extract_features_from_trade
from ai.similarity.models import SetupFeatures
from journal import trades as trades_repo


@pytest.mark.parametrize("missing", [None, float("nan"), np.nan, pd.NA, ""])
def test_infer_liquidity_kind_treats_nan_like_none(missing):
    assert _infer_liquidity_kind(missing) is None


def _row(**overrides):
    row = {
        "id": 1, "direction": "BUY", "h4_bias": "BULLISH", "h1_bias": "BULLISH",
        "m15_bias": "PULLBACK", "m5_bias": "BULLISH", "regime": "TRENDING UP",
        "market_regime": "TRENDING UP", "liquidity": "Previous Day Low swept",
        "mss": "Bullish", "displacement": "Bullish", "session": "London",
        "planned_rr": 2.5, "status": "OPEN",
    }
    row.update(overrides)
    return row


def test_extract_features_from_trade_maps_nan_to_none():
    features = extract_features_from_trade(_row(
        liquidity=float("nan"), mss=np.nan, displacement=pd.NA, planned_rr=float("nan"),
        regime=np.nan, market_regime="RANGING",
    ))
    assert features.liquidity_kind is None
    assert features.mss_direction is None
    assert features.displacement is None
    assert features.planned_rr is None
    assert features.regime == "RANGING"  # NaN regime still falls back to market_regime


def test_clean_records_turns_nan_into_none_in_float_and_string_columns():
    df = pd.DataFrame({
        "id": [1, 2],
        "planned_rr": [2.5, np.nan],                     # float column
        "liquidity": pd.Series([np.nan, np.nan], dtype=float),  # all-NULL text column read as float
        "mss": ["Bullish", np.nan],
    })
    records = engine._clean_records(df)
    assert records[1]["planned_rr"] is None
    assert records[0]["liquidity"] is None and records[1]["liquidity"] is None
    assert records[1]["mss"] is None
    assert records[0]["planned_rr"] == 2.5


def _query() -> SetupFeatures:
    return SetupFeatures(
        direction="BUY", h4_structure="BULLISH", h1_structure="BULLISH",
        m15_structure="PULLBACK", m5_structure="BULLISH", regime="TRENDING UP",
        liquidity_kind="sweep_low", mss_direction="bullish", displacement="bullish",
        session="London", planned_rr=2.5,
    )


def test_find_similar_setups_survives_nan_columns(monkeypatch):
    """Simulates the pandas-3 frame that made /api/similarity/current 500:
    a NULL liquidity column arriving as float NaN."""
    df = pd.DataFrame([_row(id=1), _row(id=2)])
    df["liquidity"] = pd.Series([np.nan, np.nan], dtype=float)
    df["planned_rr"] = [2.5, np.nan]
    df["pnl"] = [np.nan, np.nan]
    monkeypatch.setattr(engine.trades_repo, "list_trades", lambda: df)

    result = engine.find_similar_setups(_query(), min_similarity=0.0)

    assert result.considered_count == 2
    by_id = {m.trade_id: m for m in result.matches}
    assert by_id[1].entry_snapshot.liquidity_kind is None
    assert by_id[2].entry_snapshot.planned_rr is None
    assert "liquidity_kind" not in by_id[1].different_features  # not compared, not "different"
    assert by_id[1].outcome.pnl is None


def test_find_similar_setups_with_null_liquidity_in_real_db(temp_db):
    trade_payload = {
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
        "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
        "take_profit": 110.0, "planned_rr": None, "setup": "Sweep + MSS",
        "market_regime": "TRENDING UP", "notes": "", "screenshot_path": None,
    }
    context = {
        "h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
        "regime": "TRENDING UP", "liquidity": None, "mss": "Bullish",
        "displacement": "Bullish", "session": "London",
    }
    trade_id = trades_repo.create_trade(trade_payload, context)

    result = engine.find_similar_setups(_query(), min_similarity=0.0)

    assert [m.trade_id for m in result.matches] == [trade_id]
    assert result.matches[0].entry_snapshot.liquidity_kind is None
    assert result.matches[0].entry_snapshot.planned_rr is None
