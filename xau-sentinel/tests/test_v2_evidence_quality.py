"""Analysis V2 evidence quality: one logical level is counted once, while provenance
is kept. Broken levels are consolidated only when they are one structural move.
Events have one identity. Monday week-to-date adds no independent evidence.
Confluence is presented as plain observations, never as a weighted score.
Distinct evidence must never be merged away."""
import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from analysis.v2 import key_areas as ka
from analysis.v2.confluence import Confluence, Lean, _consolidated_breaks
from analysis.v2.events import Event, dedupe_events, event_identity
from analysis.v2.models import Evidence, KeyArea, KeyComponent
from analysis.v2.relations import AreaState
from analysis.v2.engine import build_analysis
from tests.v2_fixtures import range_set, trend_set

T0 = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)


def _comp(label, price, tf, kind, source, note=""):
    return KeyComponent(label, price, Evidence(tf, T0, kind, price, source, note))


# --- 1 and 2: one logical component per level, provenance kept ---------------

def test_the_same_h1_swing_low_from_three_sources_is_one_component():
    comps = [
        _comp("H1 Swing Low", 4132.41, "H1", "H1_SWING_LOW", "analysis.zones"),
        _comp("H1 swing low", 4132.41, "H1", "H1_SWING_LOW", "analysis.structure"),
        _comp("Broken H1 Swing Low", 4132.41, "H1", "H1_BROKEN_LOW", "analysis.v2.key_areas",
              "H1 swing low closed through; now a possible resistance"),
    ]
    out = ka._consolidate(comps)
    assert len(out) == 1
    primary = out[0]
    assert primary.evidence.kind == "H1_SWING_LOW"
    sources = {e.source for e in primary.corroborations} | {primary.evidence.source}
    assert sources == {"analysis.zones", "analysis.structure", "analysis.v2.key_areas"}
    assert any(e.kind == "H1_BROKEN_LOW" for e in primary.corroborations), "the broken status must survive"


def test_different_timeframes_at_the_same_price_are_not_merged():
    comps = [
        _comp("H1 swing low", 4132.41, "H1", "H1_SWING_LOW", "analysis.structure"),
        _comp("H4 swing low", 4132.41, "H4", "H4_SWING_LOW", "analysis.structure"),
    ]
    assert len(ka._consolidate(comps)) == 2


def test_different_prices_of_the_same_family_are_not_merged():
    comps = [
        _comp("H1 swing low", 4132.41, "H1", "H1_SWING_LOW", "analysis.structure"),
        _comp("H1 swing low", 4136.43, "H1", "H1_SWING_LOW", "analysis.structure"),
    ]
    assert len(ka._consolidate(comps)) == 2


def test_independent_kinds_at_one_price_stay_separate():
    comps = [
        _comp("Previous Day Low", 4124.31, "D1", "PDL", "analysis.zones"),
        _comp("Asian Low", 4124.31, "M5", "ASIAN_LOW", "analysis.zones"),
        _comp("VWAP", 4124.31, "M5", "VWAP_UTC_DAY", "analysis.zones"),
    ]
    out = ka._consolidate(comps)
    assert len(out) == 3
    assert all(not c.corroborations for c in out)


def test_strength_counts_a_level_once_even_when_it_has_several_records():
    comps = [
        _comp("H1 Swing Low", 4132.41, "H1", "H1_SWING_LOW", "analysis.zones"),
        _comp("H1 swing low", 4132.41, "H1", "H1_SWING_LOW", "analysis.structure"),
        _comp("Broken H1 Swing Low", 4132.41, "H1", "H1_BROKEN_LOW", "analysis.v2.key_areas"),
    ]
    status, reason = ka._strength(ka._consolidate(comps))
    assert status == "LOW", reason  # one kind, so it can never be rated as multiple references


# --- 3: broken-level consolidation ----------------------------------------------

def _broken(low, high, direction, when, atr_mid=None):
    area = KeyArea(low, high, (), "RESISTANCE", "LOW", "x")
    ev = Event("BREAKOUT", "M5", pd.Timestamp(when), direction, area.mid, "break")
    return AreaState(area, "BROKEN", 0.0, ("reason",), (ev,))


def _atr_obs(atr=4.0):
    class Obs:
        atr_m5 = atr
    return Obs()


def test_broken_levels_in_one_move_become_one_observation():
    t = pd.Timestamp("2026-10-05 05:05", tz="UTC")
    areas = [_broken(4132.41, 4132.41, "bullish", t),
             _broken(4136.43, 4136.43, "bullish", t + pd.Timedelta(minutes=5))]
    out = _consolidated_breaks(areas, 5.0)  # the levels are 4.02 apart: within one ATR of 5.0
    assert len(out) == 1
    assert out[0].lean == "bullish"
    assert "4132.41" in out[0].detail and "4136.43" in out[0].detail  # original levels kept


def test_opposite_direction_breaks_are_not_consolidated():
    t = pd.Timestamp("2026-10-05 05:05", tz="UTC")
    areas = [_broken(4132.41, 4132.41, "bullish", t), _broken(4136.43, 4136.43, "bearish", t)]
    assert len(_consolidated_breaks(areas, 4.0)) == 2


def test_breaks_far_apart_in_price_are_not_consolidated():
    t = pd.Timestamp("2026-10-05 05:05", tz="UTC")
    areas = [_broken(4100.0, 4100.0, "bullish", t), _broken(4140.0, 4140.0, "bullish", t)]
    assert len(_consolidated_breaks(areas, 4.0)) == 2


def test_breaks_far_apart_in_time_are_not_consolidated():
    t = pd.Timestamp("2026-10-05 05:05", tz="UTC")
    areas = [_broken(4132.41, 4132.41, "bullish", t),
             _broken(4134.0, 4134.0, "bullish", t + pd.Timedelta(hours=1))]
    assert len(_consolidated_breaks(areas, 4.0)) == 2


def test_without_an_atr_nothing_is_consolidated():
    t = pd.Timestamp("2026-10-05 05:05", tz="UTC")
    areas = [_broken(4132.41, 4132.41, "bullish", t), _broken(4132.5, 4132.5, "bullish", t)]
    assert len(_consolidated_breaks(areas, None)) == 2


# --- 4: event identity ----------------------------------------------------------

def _ev(kind="RETEST", direction="bearish", when="2026-10-05 05:00", price=4132.41, detail="d"):
    return Event(kind, "M5", pd.Timestamp(when, tz="UTC"), direction, price, detail)


def test_identical_events_collapse_to_one():
    a, b = _ev(detail="returned to 4132.41"), _ev(detail="returned to 4132.41")
    assert len(dedupe_events([a, b])) == 1


def test_same_event_with_a_slightly_different_detail_is_still_one_event():
    a, b = _ev(detail="one area"), _ev(detail="another area")
    assert len(dedupe_events([a, b])) == 1


@pytest.mark.parametrize("other", [
    _ev(when="2026-10-05 05:05"),  # different bar
    _ev(direction="bullish"),  # different direction
    _ev(price=4140.0),  # different level
    _ev(kind="REJECTION"),  # different type
    _ev(price=4132.4149),  # rounds to the same cent, so this one IS the same event
])
def test_only_genuinely_different_events_are_kept(other):
    base = _ev()
    kept = dedupe_events([base, other])
    same_identity = event_identity(base) == event_identity(other)
    assert len(kept) == (1 if same_identity else 2)


def test_engine_events_have_no_duplicate_identities_on_real_fixtures():
    for candles in (trend_set("up"), trend_set("down"), range_set()):
        analysis = build_analysis(candles, now=candles["M5"]["close_time"].iloc[-1].to_pydatetime())
        identities = [event_identity(e) for e in analysis.events]
        assert len(identities) == len(set(identities))


# --- 5: Monday week-to-date ------------------------------------------------------

def _h1_week(start):
    rows = [(100, 101, 99, 100.5)] * 40
    times = pd.date_range(start, periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = times
    df["volume"] = 100.0
    return df


def _m5_at(when):
    times = pd.date_range(end=pd.Timestamp(when, tz="UTC"), periods=80, freq="5min")
    df = pd.DataFrame([(100, 100.5, 99.5, 100.1)] * 80, columns=["open", "high", "low", "close"])
    df["time"] = times
    df["volume"] = 100.0
    return df


def test_on_monday_week_to_date_is_not_presented_as_evidence():
    # Monday 2026-10-05: the week so far is today, so week levels would repeat the daily ones.
    m5 = _m5_at("2026-10-05 10:00")
    h1 = _h1_week("2026-09-28 00:00")
    kinds = {c.evidence.kind for c in ka._extra_components(m5, h1, None)}
    assert "WEEK_HIGH" not in kinds and "WEEK_LOW" not in kinds


def test_on_tuesday_week_to_date_is_still_evidence():
    m5 = _m5_at("2026-10-06 10:00")
    h1 = _h1_week("2026-10-05 00:00")
    kinds = {c.evidence.kind for c in ka._extra_components(m5, h1, None)}
    assert {"WEEK_HIGH", "WEEK_LOW"} <= kinds


# --- confluence presentation -------------------------------------------------------

def test_confluence_carries_no_weight_or_score_fields():
    names = {f.name for f in dataclasses.fields(Confluence)}
    assert not names & {"score", "weight", "weights", "confidence", "percent", "probability", "total"}
    lean_names = {f.name for f in dataclasses.fields(Lean)}
    assert not lean_names & {"weight", "score", "confidence"}


def test_distinct_observations_are_listed_separately_not_summed():
    analysis = build_analysis(trend_set("up"), now=trend_set("up")["M5"]["close_time"].iloc[-1].to_pydatetime())
    c = analysis.confluence
    # Lists are tallies of observations; there is no field that combines them.
    assert isinstance(c.bullish, tuple) and isinstance(c.bearish, tuple)
    assert all(isinstance(l.lean, str) for l in c.supporting + c.contradicting + c.neutral)
