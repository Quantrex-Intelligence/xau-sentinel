"""V2 market-intelligence additions from the reference audit: Wilder ADX, touch-validated
zones, fair value gaps, and sweep depth/recency. Each is descriptive evidence only.
These tests also pin the imported heuristics' provenance and check that nothing here
can change A+."""
import random
import re

import pandas as pd
import pytest

from analysis.liquidity import LiquidityEvent
from analysis.sequence import evaluate_sequence
from analysis.structure import SwingPoint, compute_atr
from analysis.v2 import heuristics
from analysis.v2.adx import adx_series, latest_adx, trend_strength_state
from analysis.v2.engine import build_analysis
from analysis.v2.fvg import FILLED, OPEN, RETESTED, find_fvgs
from analysis.v2.events import fvg_events
from analysis.v2.sequence import build_sequences, sequence_wording
from analysis.v2.tested_zones import build_tested_zones
from tests.test_v2_sequence import BASE, DISP_BAR, MSS_BAR, RETRACE_BAR, _frame, _sweep
from tests.v2_fixtures import range_set, trend_set


def _walk(n=400, seed=7):
    rng = random.Random(seed)
    p, H, L, C = 100.0, [], [], []
    for _ in range(n):
        o = p
        c = o + rng.gauss(0, 0.6)
        H.append(max(o, c) + abs(rng.gauss(0, 0.3)))
        L.append(min(o, c) - abs(rng.gauss(0, 0.3)))
        C.append(c)
        p = c
    return H, L, C


# --- 1. ADX -------------------------------------------------------------------------

def test_adx_matches_the_reference_implementation_on_a_fixed_series():
    """Golden value taken from the reference project's signals/indicators.py (Wilder ADX)
    on the same seeded bars. Agreement to 4 dp shows the formula is the standard one."""
    H, L, C = _walk()
    values = adx_series(H, L, C, 14)
    assert values[27] is not None and values[26] is None  # first value after 2*period-1 bars
    assert round(values[-1], 4) == 17.6311


def test_adx_is_bounded_and_needs_warm_up():
    H, L, C = _walk()
    values = adx_series(H, L, C, 14)
    defined = [v for v in values if v is not None]
    assert defined and all(0.0 <= v <= 100.0 for v in defined)
    assert all(v is None for v in values[:27])


def test_adx_is_high_in_a_strong_trend_and_low_in_a_flat_range():
    up = [100 + i * 0.5 for i in range(120)]
    trend = adx_series([x + 0.3 for x in up], [x - 0.3 for x in up], up, 14)[-1]
    flat_c = [100 + (0.2 if i % 2 else -0.2) for i in range(120)]
    flat = adx_series([x + 0.3 for x in flat_c], [x - 0.3 for x in flat_c], flat_c, 14)[-1]
    assert trend > 40 and flat < 20


def test_adx_uses_only_bars_up_to_each_point_no_lookahead():
    H, L, C = _walk()
    full = adx_series(H, L, C, 14)
    prefix = adx_series(H[:200], L[:200], C[:200], 14)
    assert all(a == b for a, b in zip(prefix, full[:200]))


def test_adx_band_labels_follow_the_imported_cutoffs():
    assert trend_strength_state(None) == "UNKNOWN"
    assert trend_strength_state(10.0) == "WEAK_TREND"
    assert trend_strength_state(25.0) == "DEVELOPING_TREND"
    assert trend_strength_state(40.0) == "STRONG_TREND"


def test_latest_adx_on_a_short_frame_is_none_rather_than_a_guess():
    assert latest_adx(_frame(BASE[:10])) is None


def test_context_exposes_trend_strength_without_any_direction():
    analysis = build_analysis(trend_set("up"), now=trend_set("up")["M5"]["close_time"].iloc[-1].to_pydatetime())
    ts = analysis.context.trend_strength
    assert ts.state in {"UNKNOWN", "WEAK_TREND", "DEVELOPING_TREND", "STRONG_TREND"}
    assert not re.search(r"bullish|bearish|buy|sell", ts.detail, re.IGNORECASE)


# --- 2. Touch-validated zones ----------------------------------------------------------

def _h1_with_lows(lows_by_index, n=40, base=101.0):
    rows = []
    for i in range(n):
        low = lows_by_index.get(i, base)
        rows.append((base, base + 0.5, low, base + 0.1))
    t = pd.date_range("2026-01-05", periods=n, freq="60min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = t
    return df


def _v_low(depth_index, value):
    """A low pivot: lower than its neighbours within the swing lookback."""
    return {depth_index - 2: value + 1, depth_index - 1: value + 0.5, depth_index: value,
            depth_index + 1: value + 0.5, depth_index + 2: value + 1}


def test_clustered_pivots_within_the_atr_width_form_one_tested_support_zone():
    lows = {}
    for idx, val in ((6, 100.0), (14, 100.2), (22, 100.1)):
        lows.update(_v_low(idx, val))
    zones = build_tested_zones(_h1_with_lows(lows), atr_value=2.0)
    support = [z for z in zones if z.kind == "SUPPORT"]
    assert len(support) == 1
    assert support[0].touch_count == 3
    assert support[0].low == pytest.approx(100.0) and support[0].high == pytest.approx(100.2)


def test_a_single_pivot_is_not_a_tested_zone():
    lows = _v_low(10, 100.0)
    assert [z for z in build_tested_zones(_h1_with_lows(lows), atr_value=2.0) if z.kind == "SUPPORT"] == []


def test_pivots_farther_apart_than_the_atr_width_do_not_merge():
    lows = {}
    for idx, val in ((6, 100.0), (14, 100.6), (22, 100.0)):
        lows.update(_v_low(idx, val))
    tight = build_tested_zones(_h1_with_lows(lows), atr_value=1.0)  # width 0.5: 100.0 and 100.6 stay apart
    wide = build_tested_zones(_h1_with_lows(lows), atr_value=2.0)   # width 1.0: all three merge
    assert [z.touch_count for z in tight if z.kind == "SUPPORT"] == [2]
    assert [z.touch_count for z in wide if z.kind == "SUPPORT"] == [3]


def test_zone_provenance_keeps_the_pivot_times_and_prices():
    lows = {}
    for idx, val in ((6, 100.0), (14, 100.1)):
        lows.update(_v_low(idx, val))
    h1 = _h1_with_lows(lows)
    zone = next(z for z in build_tested_zones(h1, atr_value=2.0) if z.kind == "SUPPORT")
    assert {t.price for t in zone.touches} == {100.0, 100.1}
    assert {pd.Timestamp(t.time) for t in zone.touches} == {pd.Timestamp(h1["time"].iloc[6]), pd.Timestamp(h1["time"].iloc[14])}


def test_no_zones_without_a_usable_atr():
    assert build_tested_zones(_h1_with_lows({}), atr_value=0.0) == ()
    assert build_tested_zones(_h1_with_lows({}), atr_value=None) == ()


# --- 3. Fair value gaps ----------------------------------------------------------------------

def _bars(rows):
    t = pd.date_range("2026-01-05", periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = t
    df["volume"] = 100.0
    return df


BULL_GAP = [(99.0, 100.0, 98.8, 99.9), (99.9, 101.5, 99.8, 101.4), (101.4, 102.0, 101.0, 101.8)]


def test_bullish_gap_is_detected_on_the_third_bar_between_the_outer_wicks():
    gaps = find_fvgs(_bars(BULL_GAP + [(101.8, 102.2, 101.2, 102.0)]), lookback=30)
    bull = [g for g in gaps if g.direction == "bullish"]
    assert len(bull) == 1
    assert (bull[0].low, bull[0].high) == (100.0, 101.0)
    assert bull[0].formed_at == pd.Timestamp("2026-01-05 00:10", tz="UTC")


def test_bearish_gap_is_the_mirror_of_the_bullish_one():
    mirror = [(200 - o, 200 - l, 200 - h, 200 - c) for (o, h, l, c) in BULL_GAP]
    gaps = find_fvgs(_bars(mirror + [(98.2, 98.8, 98.4, 98.2)]), lookback=30)
    bear = [g for g in gaps if g.direction == "bearish"]
    assert len(bear) == 1
    assert (bear[0].low, bear[0].high) == (99.0, 100.0)


def test_gap_status_moves_from_open_to_retested_to_filled_on_later_closed_bars():
    base = BULL_GAP
    open_gap = find_fvgs(_bars(base + [(101.8, 102.5, 101.7, 102.3)]), lookback=30)[0]
    assert open_gap.status == OPEN and open_gap.retested_at is None
    retested = find_fvgs(_bars(base + [(101.8, 102.0, 100.5, 101.6)]), lookback=30)[0]
    assert retested.status == RETESTED and retested.retested_at is not None
    filled = find_fvgs(_bars(base + [(101.8, 102.0, 100.5, 101.6), (101.0, 101.1, 99.5, 99.8)]), lookback=30)[0]
    assert filled.status == FILLED and filled.filled_at is not None


def test_gap_detection_has_no_lookahead():
    series = _bars(BULL_GAP + [(101.8, 102.5, 101.7, 102.3), (102.3, 103.0, 100.0, 100.4)])
    early = find_fvgs(series.iloc[:4], lookback=30)[0]
    late = find_fvgs(series, lookback=30)[0]
    assert early.formed_at == late.formed_at
    assert early.status == OPEN  # nothing after the prefix can have changed what was known at bar 3


def test_gaps_older_than_the_lookback_are_not_reported():
    rows = BULL_GAP + [(101.8, 102.0, 101.6, 101.9)] * 40
    assert find_fvgs(_bars(rows), lookback=10) == ()


def test_fvg_events_are_emitted_as_v2_events_with_status_in_the_detail():
    events = fvg_events(_bars(BULL_GAP + [(101.8, 102.0, 100.5, 101.6)]))
    assert events and events[0].kind == "FVG" and events[0].direction == "bullish"
    assert "retested" in events[0].detail


# --- 4. Sweep depth and recency --------------------------------------------------------------

def test_sweep_depth_and_recency_are_measured_against_the_bars_not_guessed():
    df = _frame(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    sweep = _sweep(df, bar=len(BASE) - 1)
    seq = build_sequences(df, [sweep])[0]
    atr_at_sweep = float(compute_atr(df).iloc[len(BASE) - 1])
    expected_depth = (99.0 - float(df["low"].iloc[len(BASE) - 1])) / atr_at_sweep
    assert seq.sweep_depth_atr == pytest.approx(round(expected_depth, 4))
    assert seq.bars_since_sweep == (len(df) - 1) - (len(BASE) - 1)
    assert seq.bars_sweep_to_shift == 1


def test_depth_and_recency_are_descriptive_and_leave_the_a_plus_evidence_untouched():
    df = _frame(BASE + [MSS_BAR, DISP_BAR, RETRACE_BAR])
    sweep = _sweep(df, bar=len(BASE) - 1)
    seq = build_sequences(df, [sweep])[0]
    assert seq.evidence == evaluate_sequence(df, sweep, "BUY")


def test_sequence_wording_states_depth_and_timing_as_facts():
    df = _frame(BASE + [MSS_BAR, DISP_BAR])
    seq = build_sequences(df, [_sweep(df, bar=len(BASE) - 1)])[0]
    evidence = sequence_wording(seq)["evidence"]
    assert evidence.startswith("Sweep pierced the level by ") and "ATR" in evidence
    assert not re.search(r"\b(buy|sell|enter|should|will|likely)\b", evidence, re.IGNORECASE)


# --- Provenance and boundaries -------------------------------------------------------------

def test_every_imported_heuristic_is_documented_and_marked_unvalidated():
    names = [n for n in dir(heuristics) if isinstance(getattr(heuristics, n), heuristics.Heuristic)]
    assert names
    for name in names:
        h = getattr(heuristics, name)
        assert h.validated is False, name
        assert h.source.strip(), name
    assert "Not validated" in heuristics.PROVENANCE_NOTE


def test_no_new_reference_indicators_were_added_to_v2():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "analysis" / "v2"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    for forbidden in ("def rsi", "def macd", "def ema(", "def bollinger"):
        assert forbidden not in text, forbidden


def test_a_chain_of_nearby_pivots_cannot_stretch_one_zone_beyond_the_cluster_width():
    """Each pivot is within the width of the previous one, but the whole chain spans more than
    one width. The zone must be split rather than chained into one wide level."""
    lows = {}
    for idx, val in ((4, 100.0), (8, 100.4), (12, 100.8), (16, 101.2), (20, 101.6)):
        lows.update(_v_low(idx, val))
    zones = [z for z in build_tested_zones(_h1_with_lows(lows), atr_value=1.0) if z.kind == "SUPPORT"]
    assert zones, "the chain must still produce tested zones"
    assert all(z.high - z.low <= 0.5 + 1e-9 for z in zones)  # width is 0.5 at ATR 1.0
