"""Tests for ai/tools/market_tools.py: each tool traces to
api.snapshot.build_snapshot() (the same aggregation point every REST market
route already uses), returns data_available=True with a timestamp when data
exists, and degrades to data_available=False with a reason on a data
error — never a fabricated value."""
from unittest.mock import patch

from api.schemas import ConnectionOut, MarketSnapshotOut, RiskOut
from ai.tools import market_tools


def test_get_market_state_returns_data_when_snapshot_is_healthy(temp_db):
    result = market_tools.get_market_state({})
    assert result.data_available is True
    assert result.timestamp is not None
    assert "price" in result.data


def test_get_current_setup_returns_data_when_snapshot_is_healthy(temp_db):
    result = market_tools.get_current_setup({})
    assert result.data_available is True
    assert "state" in result.data


def test_get_market_structure_returns_per_timeframe_data(temp_db):
    result = market_tools.get_market_structure({})
    assert result.data_available is True
    assert "H1" in result.data["structure"] or "M5" in result.data["structure"]


def test_get_liquidity_returns_sweep_and_equal_level_lists(temp_db):
    result = market_tools.get_liquidity({})
    assert result.data_available is True
    assert "sweeps" in result.data
    assert "equal_levels" in result.data


def test_get_key_zones_degrades_gracefully_when_no_zones_available():
    fake_snapshot = MarketSnapshotOut(
        connection=ConnectionOut(label="mock", connected=True, mode="mock"),
        price=None, structure={}, regime=None, zones={},
        liquidity={"sweeps": [], "equal_levels": []}, setup=None,
        risk=RiskOut(balance=50000, risk_per_trade_pct=0.3, today_r=0.0),
        data_error="Market data unavailable.",
    )
    with patch.object(market_tools, "build_snapshot", return_value=fake_snapshot):
        result = market_tools.get_key_zones({})
    assert result.data_available is False
    assert result.reason


def test_get_market_state_degrades_gracefully_on_data_error():
    fake_snapshot = MarketSnapshotOut(
        connection=ConnectionOut(label="mock", connected=True, mode="mock"),
        price=None, structure={}, regime=None, zones={},
        liquidity={"sweeps": [], "equal_levels": []}, setup=None,
        risk=RiskOut(balance=50000, risk_per_trade_pct=0.3, today_r=0.0),
        data_error="Simulated market data outage.",
    )
    with patch.object(market_tools, "build_snapshot", return_value=fake_snapshot):
        result = market_tools.get_market_state({})
    assert result.data_available is False
    assert result.reason == "Simulated market data outage."
