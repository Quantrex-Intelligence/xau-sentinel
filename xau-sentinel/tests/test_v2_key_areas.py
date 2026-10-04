"""Analysis V2 increment 2: unified key areas."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from analysis.v2 import key_areas as ka
from analysis.v2.models import Evidence, KeyComponent

T = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


def _comp(label, price, tf, kind, source="analysis.zones"):
    return KeyComponent(label, price, Evidence(tf, T, kind, price, source))


def _frames():
    from mt5.market_data import _mock_candles
    return (_mock_candles("M5", 700), _mock_candles("H1", 320), _mock_candles("H4", 320))


def _patch_components(monkeypatch, comps, atr=2.0):
    monkeypatch.setattr(ka, "_components", lambda m5, h1, h4: list(comps))
    frame = pd.DataFrame({"high": [atr + 1] * 30, "low": [1.0] * 30, "close": [atr] * 30,
                          "time": pd.date_range("2026-10-02", periods=30, freq="5min", tz="UTC")})
    return frame


def test_nearby_references_merge_into_one_area(monkeypatch):
    comps = [_comp("PDH", 3010.0, "D1", "PDH"),
             _comp("H1 swing high", 3010.3, "H1", "H1_SWING_HIGH", "analysis.structure"),
             _comp("EQUAL HIGHS", 3010.4, "M5", "EQUAL_HIGH", "analysis.liquidity")]
    frame = _patch_components(monkeypatch, comps, atr=2.0)
    areas = ka.build_key_areas(frame, frame, frame, current_price=3000.0)
    assert len(areas) == 1
    assert areas[0].low == 3010.0 and areas[0].high == 3010.4
    assert {c.label for c in areas[0].components} == {"PDH", "H1 swing high", "EQUAL HIGHS"}


def test_distant_references_stay_separate(monkeypatch):
    comps = [_comp("PDH", 3010.0, "D1", "PDH"), _comp("PDL", 2980.0, "D1", "PDL")]
    frame = _patch_components(monkeypatch, comps, atr=2.0)
    areas = ka.build_key_areas(frame, frame, frame, current_price=3000.0)
    assert len(areas) == 2


def test_strength_follows_explicit_rules(monkeypatch):
    one = [_comp("PDH", 3010.0, "D1", "PDH")]
    two_kinds = one + [_comp("EQ", 3010.1, "M5", "EQUAL_HIGH", "analysis.liquidity")]
    three_kinds_two_tf = two_kinds + [_comp("H1 SH", 3010.2, "H1", "H1_SWING_HIGH", "analysis.structure")]
    for comps, expected in ((one, "LOW"), (two_kinds, "MODERATE"), (three_kinds_two_tf, "HIGH")):
        frame = _patch_components(monkeypatch, comps, atr=2.0)
        status = ka.build_key_areas(frame, frame, frame, current_price=3000.0)[0].strength_status
        assert status == expected


def test_side_is_relative_to_current_price(monkeypatch):
    comps = [_comp("PDH", 3010.0, "D1", "PDH"), _comp("PDL", 2980.0, "D1", "PDL")]
    frame = _patch_components(monkeypatch, comps, atr=2.0)
    sides = {a.side for a in ka.build_key_areas(frame, frame, frame, current_price=3000.0)}
    assert sides == {"RESISTANCE", "SUPPORT"}


def test_relationship_inside_approaching_far():
    from analysis.v2.models import KeyArea
    area = KeyArea(3010.0, 3012.0, (), "RESISTANCE", "LOW", "x")
    assert ka.relationship(area, 3011.0, atr=2.0).relation == "INSIDE"
    assert ka.relationship(area, 3008.0, atr=2.0).relation == "APPROACHING"  # 1 ATR below
    assert ka.relationship(area, 3000.0, atr=2.0).relation == "FAR"
    assert ka.relationship(area, 3000.0, atr=2.0).distance_atr == pytest.approx(5.0)


def test_no_areas_without_usable_atr(monkeypatch):
    frame = _patch_components(monkeypatch, [_comp("PDH", 3010.0, "D1", "PDH")], atr=2.0)
    flat = frame.copy()
    flat["high"] = flat["low"] = flat["close"] = 1.0  # zero true range -> zero ATR
    assert ka.build_key_areas(flat, flat, flat, current_price=3000.0) == []


def test_real_pipeline_is_deterministic_and_keeps_provenance():
    m5, h1, h4 = _frames()
    price = float(m5["close"].iloc[-1])
    first = ka.build_key_areas(m5, h1, h4, price)
    assert first, "real pipeline produced no key areas; the test would be vacuous"
    second = ka.build_key_areas(m5, h1, h4, price)
    assert [(a.low, a.high) for a in first] == [(a.low, a.high) for a in second]
    assert all(c.evidence.source for a in first for c in a.components)
    assert all(c.evidence.timeframe in {"M5", "M15", "H1", "H4", "D1"} for a in first for c in a.components)
    assert all(a.low <= a.high for a in first)
    assert all(a.strength_reason for a in first)


def test_only_recent_swings_become_references():
    from analysis.structure import SwingPoint
    import numpy as np
    swings = [SwingPoint(i, pd.Timestamp("2026-10-01", tz="UTC") + pd.Timedelta(hours=i),
                         3000.0 + i, "high" if i % 2 == 0 else "low") for i in range(10)]
    frame = pd.DataFrame({"high": np.linspace(3000, 3010, 30), "low": np.linspace(2990, 3000, 30),
                          "close": np.linspace(2995, 3005, 30),
                          "time": pd.date_range("2026-10-01", periods=30, freq="h", tz="UTC")})
    original = ka.find_swing_points
    ka.find_swing_points = lambda df, lookback=None: swings
    try:
        comps = ka._components(_frames()[0], frame, frame)
    finally:
        ka.find_swing_points = original
    h1_high = [c for c in comps if c.evidence.kind == "H1_SWING_HIGH"]
    h1_low = [c for c in comps if c.evidence.kind == "H1_SWING_LOW"]
    assert len(h1_high) == 2 and len(h1_low) == 2
    assert max(c.price for c in h1_high) == 3008.0  # the latest highs are i=6 and i=8
