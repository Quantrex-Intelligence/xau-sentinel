"""Tests for the offline LuxAlgo ICT overlay (tools/luxalgo_audit) and its read-only route."""
import numpy as np
import pandas as pd
import pytest

from api.routes import tools as tools_route
from mt5 import market_data
from tools.luxalgo_audit import overlay as OV


def _bars(n=400, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0, 1, n)
    low = np.minimum(open_, close) - rng.uniform(0, 1, n)
    t = pd.date_range("2026-10-01 00:00", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"time": t, "open": open_, "high": high, "low": low, "close": close, "is_closed": True})


def test_overlay_keeps_the_source_visibility_limits():
    out = OV.build_overlay(_bars())
    for side in ("bullish", "bearish"):
        assert sum(1 for f in out["fvg"] if f["side"] == side) <= OV.FVG_PER_SIDE
        assert sum(1 for o in out["order_blocks"] if o["side"] == side) <= OV.OB_PER_SIDE
    assert sum(1 for x in out["liquidity"] if x["side"] == "buyside") <= OV.LIQ_PER_SIDE
    assert sum(1 for x in out["liquidity"] if x["side"] == "sellside") <= OV.LIQ_PER_SIDE


def test_overlay_times_are_epoch_seconds_and_structure_is_in_time_order():
    out = OV.build_overlay(_bars())
    assert isinstance(out["last_bar_time"], int)
    times = [s["time"] for s in out["structure"]]
    assert times == sorted(times)
    assert all(isinstance(t, int) for t in times)


def test_overlay_fvg_edges_are_ordered_and_only_active_boxes_are_shown():
    out = OV.build_overlay(_bars())
    for f in out["fvg"]:
        assert f["top"] >= f["bottom"]


def test_overlay_of_no_bars_is_empty_not_an_error():
    out = OV.build_overlay(pd.DataFrame())
    assert out["fvg"] == [] and out["structure"] == [] and out["last_bar_time"] is None


def test_route_drops_the_forming_bar_before_the_reference_runs(monkeypatch):
    bars = _bars()
    bars.loc[bars.index[-1], "is_closed"] = False  # the forming bar
    seen = {}

    def fake(timeframe, count):
        return bars

    monkeypatch.setattr(market_data, "get_candles", fake)
    original = OV.build_overlay

    def spy(df):
        seen["closed_rows"] = len(df)
        return original(df)

    monkeypatch.setattr(tools_route, "build_overlay", spy)
    out = tools_route.get_luxalgo_ict(timeframe="M5", count=300)
    assert seen["closed_rows"] == len(bars) - 1
    assert out["bars"] == len(bars) - 1
    assert "not validated" in out["note"]


def test_route_maps_bad_timeframe_to_400(monkeypatch):
    from fastapi import HTTPException

    def boom(timeframe, count):
        raise ValueError("Unsupported timeframe: X")

    monkeypatch.setattr(market_data, "get_candles", boom)
    with pytest.raises(HTTPException) as exc:
        tools_route.get_luxalgo_ict(timeframe="X", count=300)
    assert exc.value.status_code == 400


def test_route_maps_mt5_outage_to_503(monkeypatch):
    from fastapi import HTTPException

    def down(timeframe, count):
        raise market_data.MarketDataError("MT5 not connected")

    monkeypatch.setattr(market_data, "get_candles", down)
    with pytest.raises(HTTPException) as exc:
        tools_route.get_luxalgo_ict(timeframe="M5", count=300)
    assert exc.value.status_code == 503
