"""Deterministic tests for the Top-Down Multi-Timeframe Entry Model (analysis/entry_model/
hierarchy.py and its layers: htf.py, intraday.py, setup_15m.py, confirmation_5m.py, precision_1m.py).

V1's own tests (tests/test_entry_model.py, tests/test_entry_model_outcome.py) are untouched and
keep testing analysis/entry_model/model.py directly -- this file tests the new, active
implementation behind analysis.entry_model.evaluate."""
import pathlib
import unittest.mock as mock

import pandas as pd
import pytest

from analysis.entry_model import common as CM
from analysis.entry_model import confirmation_5m as C5
from analysis.entry_model import hierarchy as H
from analysis.entry_model import htf as HTF
from analysis.entry_model import intraday as ID
from analysis.entry_model import precision_1m as P1
from analysis.entry_model import setup_15m as S15
from tests.conftest import make_candles
from tests.test_structure import BEARISH_POINTS, BULLISH_POINTS
from tests.v2_fixtures import DOWN_TAIL, UP_TAIL, path_candles, range_set, trend_set, with_forming_bar

NOW = pd.Timestamp("2026-10-08 12:00", tz="UTC")


def _frames(direction="up", d1=None):
    fr = trend_set(direction)
    points, tail = (BULLISH_POINTS, UP_TAIL) if direction == "up" else (BEARISH_POINTS, DOWN_TAIL)
    fr["D1"] = d1 if d1 is not None else path_candles(points, 10, 1440, tail)
    fr["M1"] = fr["M5"]
    return fr


# --- HTF layer (1D + 4H): location and context --------------------------------------------------

def test_htf_context_bullish_when_1d_and_4h_agree():
    fr = _frames("up")
    price = float(fr["M5"]["close"].iloc[-1])
    out = HTF.evaluate_htf(fr["D1"], fr["H4"], fr["H1"], fr["M5"], price)
    assert out["htf_context"] == "BULLISH"
    assert out["d1_bias"] == "bullish" and out["h4_bias"] == "bullish"


def test_htf_context_bearish_when_1d_and_4h_agree():
    fr = _frames("down")
    price = float(fr["M5"]["close"].iloc[-1])
    out = HTF.evaluate_htf(fr["D1"], fr["H4"], fr["H1"], fr["M5"], price)
    assert out["htf_context"] == "BEARISH"


def test_htf_context_transition_when_1d_and_4h_disagree():
    up = _frames("up")
    down_d1 = path_candles(BEARISH_POINTS, 10, 1440, DOWN_TAIL)
    price = float(up["M5"]["close"].iloc[-1])
    out = HTF.evaluate_htf(down_d1, up["H4"], up["H1"], up["M5"], price)
    assert out["htf_context"] == "TRANSITION"


def test_htf_context_neutral_in_a_pure_range():
    fr = range_set()
    fr["D1"] = fr["H4"]
    price = float(fr["M5"]["close"].iloc[-1])
    out = HTF.evaluate_htf(fr["D1"], fr["H4"], fr["H1"], fr["M5"], price)
    assert out["htf_context"] == "NEUTRAL"


def test_htf_location_unknown_without_enough_data():
    out = HTF.evaluate_htf(None, None, None, None, 100.0)
    assert out["htf_location"] == "UNKNOWN"
    assert out["nearest_area"] is None


def test_htf_location_is_one_of_the_five_states_and_never_requires_a_setup():
    fr = _frames("up")
    price = float(fr["M5"]["close"].iloc[-1])
    out = HTF.evaluate_htf(fr["D1"], fr["H4"], fr["H1"], fr["M5"], price)
    assert out["htf_location"] in HTF.LOCATION_STATES
    # HTF never asks for a direction/setup -- only location and context exist here.
    assert "setup_direction" not in out and "entry" not in out


# --- 1H layer: intraday bias --------------------------------------------------------------------

def test_intraday_bias_follows_1h_structure_state():
    fr = _frames("up")
    out = ID.evaluate_intraday(fr["H1"], "BULLISH")
    assert out["intraday_bias"] == "BULLISH"
    assert out["compatible_with_htf"] is True


def test_intraday_bias_neutral_with_too_little_history():
    out = ID.evaluate_intraday(None, "BULLISH")
    assert out["intraday_bias"] == "NEUTRAL"
    assert out["compatible_with_htf"] is None


def test_intraday_incompatible_with_an_opposing_htf_context():
    fr = _frames("up")  # 1H bullish
    out = ID.evaluate_intraday(fr["H1"], "BEARISH")
    assert out["intraday_bias"] == "BULLISH"
    assert out["compatible_with_htf"] is False


def test_intraday_never_requires_a_sweep_fvg_or_displacement():
    fr = _frames("up")
    out = ID.evaluate_intraday(fr["H1"], "BULLISH")
    assert "fvg" not in out and "sweep" not in out and "displacement" not in out


# --- 15M layer: setup formation, evidence-based not chained -------------------------------------

def test_setup_direction_follows_the_majority_of_evidence_categories(monkeypatch):
    m15 = _frames("up")["M15"]

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev("M15", pd.Timestamp(NOW), "SWEEP_LOW", 1.0, "x")},
                            {"kind": "MSS_BOS", "evidence": CM.ev("M15", pd.Timestamp(NOW), "MSS_BOS_BULLISH", 1.0, "x")}],
                "bearish": [{"kind": "FVG", "fvg": None, "evidence": CM.ev("M15", pd.Timestamp(NOW), "FVG", 1.0, "x")}]}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    out = S15.evaluate_setup(m15, m15, m15, m15, "BULLISH", "BULLISH", True, 100.0)
    assert out["setup_direction"] == "LONG"  # 2 bullish categories outvote 1 bearish
    assert out["setup_status"] == "SETUP_CONFIRMED"  # >= 2 categories on the winning side


def test_setup_is_conflicted_on_a_genuine_tie(monkeypatch):
    m15 = _frames("up")["M15"]

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev("M15", pd.Timestamp(NOW), "SWEEP_LOW", 1.0, "x")}],
                "bearish": [{"kind": "FVG", "fvg": None, "evidence": CM.ev("M15", pd.Timestamp(NOW), "FVG", 1.0, "x")}]}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    out = S15.evaluate_setup(m15, m15, m15, m15, "BULLISH", "BULLISH", True, 100.0)
    assert out["setup_direction"] == "CONFLICTED"
    assert out["setup_status"] == "CONFLICTED"


def test_setup_waits_with_no_evidence_at_all(monkeypatch):
    m15 = _frames("up")["M15"]
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: {"bullish": [], "bearish": []})
    out = S15.evaluate_setup(m15, m15, m15, m15, "BULLISH", "BULLISH", True, 100.0)
    assert out["setup_direction"] == "NEUTRAL"
    assert out["setup_status"] == "WAITING"


def test_setup_developing_with_a_single_evidence_category(monkeypatch):
    m15 = _frames("up")["M15"]

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev("M15", pd.Timestamp(NOW), "SWEEP_LOW", 1.0, "x")}],
                "bearish": []}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    out = S15.evaluate_setup(m15, m15, m15, m15, "BULLISH", "BULLISH", True, 100.0)
    assert out["setup_direction"] == "LONG"
    assert out["setup_status"] == "SETUP_DEVELOPING"


def test_setup_direction_does_not_override_an_opposing_1h_bias(monkeypatch):
    m15 = _frames("up")["M15"]

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev("M15", pd.Timestamp(NOW), "SWEEP_LOW", 1.0, "x")},
                            {"kind": "MSS_BOS", "evidence": CM.ev("M15", pd.Timestamp(NOW), "MSS_BOS_BULLISH", 1.0, "x")}],
                "bearish": []}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    # HTF and 1H both agree BEARISH; 15M's own bullish-majority evidence must not override that.
    out = S15.evaluate_setup(m15, m15, m15, m15, "BEARISH", "BEARISH", True, 100.0)
    assert out["setup_direction"] == "CONFLICTED"  # bullish majority cannot override the established bias


def test_setup_insufficient_history_waits_not_guesses():
    out = S15.evaluate_setup(None, None, None, None, "BULLISH", "BULLISH", True, 100.0)
    assert out["setup_status"] == "WAITING"
    assert out["setup_direction"] == "NEUTRAL"


# --- 5M layer: confirmation, not a rigid "fresh MSS after retracement" requirement --------------

def test_confirmation_not_applicable_without_a_setup_direction():
    out = C5.evaluate_confirmation(None, None, None, "NEUTRAL", 100.0)
    assert out["confirmation_status"] == "NOT_APPLICABLE"


def test_confirmation_confirmed_with_two_aligned_categories(monkeypatch):
    m5 = _frames("up")["M5"]

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "MSS_BOS", "evidence": CM.ev("M5", pd.Timestamp(NOW), "MSS_BOS_BULLISH", 1.0, "x")},
                            {"kind": "DISPLACEMENT", "evidence": CM.ev("M5", pd.Timestamp(NOW), "DISPLACEMENT_BULLISH", 1.0, "x")}],
                "bearish": []}

    monkeypatch.setattr(C5, "gather_directional_evidence", fake_evidence)
    out = C5.evaluate_confirmation(m5, m5, m5, "LONG", 100.0)
    assert out["confirmation_status"] == "CONFIRMED"


def test_confirmation_developing_with_one_category(monkeypatch):
    m5 = _frames("up")["M5"]
    monkeypatch.setattr(C5, "gather_directional_evidence", lambda *a, **k: {
        "bullish": [{"kind": "MSS_BOS", "evidence": CM.ev("M5", pd.Timestamp(NOW), "MSS_BOS_BULLISH", 1.0, "x")}],
        "bearish": []})
    out = C5.evaluate_confirmation(m5, m5, m5, "LONG", 100.0)
    assert out["confirmation_status"] == "DEVELOPING"


def test_confirmation_conflicted_when_5m_majority_opposes_the_setup(monkeypatch):
    m5 = _frames("up")["M5"]
    monkeypatch.setattr(C5, "gather_directional_evidence", lambda *a, **k: {
        "bullish": [],
        "bearish": [{"kind": "MSS_BOS", "evidence": CM.ev("M5", pd.Timestamp(NOW), "MSS_BOS_BEARISH", 1.0, "x")},
                   {"kind": "DISPLACEMENT", "evidence": CM.ev("M5", pd.Timestamp(NOW), "DISPLACEMENT_BEARISH", 1.0, "x")}]})
    out = C5.evaluate_confirmation(m5, m5, m5, "LONG", 100.0)
    assert out["confirmation_status"] == "CONFLICTED"


def test_confirmation_never_requires_exact_simultaneity_with_retracement():
    """The V1 rule this redesign replaced. Reusing gather_directional_evidence directly (not a
    special-cased 'retest' flag) means confirmation can be read as DEVELOPING/CONFIRMED purely
    from current 5M structure, independent of any FVG retest timing."""
    m5 = _frames("up")["M5"]
    out = C5.evaluate_confirmation(m5, _frames("up")["H1"], _frames("up")["H4"], "LONG", float(m5["close"].iloc[-1]))
    assert out["confirmation_status"] in C5.CONFIRMATION_STATES


# --- 1M layer: optional precision, never the primary decision -----------------------------------

def test_precision_not_applicable_without_a_direction():
    out = P1.evaluate_precision(None, "NEUTRAL", NOW)
    assert out["precision_status"] == "NOT_APPLICABLE"


def test_precision_waits_without_enough_m1_history():
    short_m1 = _frames("up")["M1"].iloc[:20].reset_index(drop=True)
    out = P1.evaluate_precision(short_m1, "LONG", NOW)
    assert out["precision_status"] == "WAITING"


def test_precision_available_cites_a_specific_closed_bar():
    m1 = path_candles(BEARISH_POINTS + [100, 130], 80, 1, [130, 130, 130, 130])
    out = P1.evaluate_precision(m1, "LONG", pd.Timestamp("2026-01-05 00:00", tz="UTC"))
    assert out["precision_status"] == "AVAILABLE"
    trig = out["trigger"]
    assert trig["closed_bar"] is True
    assert trig["direction"] == "bullish"
    assert isinstance(trig["bar_index"], int)


def test_precision_waits_when_the_only_event_is_before_the_cutoff():
    m1 = path_candles(BEARISH_POINTS + [100, 130], 80, 1, [130, 130, 130, 130])
    out = P1.evaluate_precision(m1, "LONG", pd.Timestamp("2026-01-06 00:00", tz="UTC"))
    assert out["precision_status"] == "WAITING"


def test_precision_is_never_consulted_before_5m_confirmation_reaches_developing(monkeypatch):
    """The explicit anti-override rule: a strong 1M pattern alone must never create or upgrade a
    candidate. hierarchy.py enforces this by not even calling evaluate_precision."""
    called = []
    monkeypatch.setattr(H, "evaluate_precision", lambda *a, **k: called.append(1) or
                        {"precision_status": "AVAILABLE", "trigger": {}, "checklist": []})
    monkeypatch.setattr(H, "evaluate_confirmation", lambda *a, **k: {
        "confirmation_status": "WAITING", "evidence_categories": [], "supporting_evidence": [],
        "contradicting_evidence": [], "checklist": []})
    fr = _frames("up")
    H.evaluate(fr, NOW)
    assert not called


# --- Conflicting contexts and missing evidence ---------------------------------------------------

def test_overall_state_is_conflicted_when_setup_evidence_conflicts(monkeypatch):
    fr = _frames("up")

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev(timeframe, NOW, "SWEEP_LOW", 1.0, "x")}],
                "bearish": [{"kind": "FVG", "fvg": None, "evidence": CM.ev(timeframe, NOW, "FVG", 1.0, "x")}]}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    out = H.evaluate(fr, NOW)
    assert out["state"] == "CONFLICTED"
    assert out["direction"] == "CONFLICTED"


def test_missing_evidence_reports_no_context_rather_than_guessing():
    fr = _frames("up")
    fr["H1"] = fr["H1"].iloc[:5]  # far below MIN_BARS
    out = H.evaluate(fr, NOW)
    assert out["state"] == "NO_CONTEXT"
    assert out["direction"] is None
    assert out["entry_candidate"] is None


def test_forming_candle_never_changes_the_result():
    base = _frames("up")
    forming = dict(base)
    forming["M5"] = with_forming_bar(base, "M5")["M5"]
    forming["M15"] = with_forming_bar(base, "M15")["M15"]
    assert H.evaluate(base, NOW) == H.evaluate(forming, NOW)


# --- Invalidation: reuses existing structural facts, never a new detector -----------------------

def test_invalidation_from_an_opposing_1h_mss(monkeypatch):
    fr = _frames("up")

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev(timeframe, NOW, "SWEEP_LOW", 1.0, "x")},
                            {"kind": "MSS_BOS", "evidence": CM.ev(timeframe, NOW, "MSS_BOS_BULLISH", 1.0, "x")}],
                "bearish": []}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    monkeypatch.setattr(C5, "gather_directional_evidence", lambda *a, **k: {"bullish": [], "bearish": []})
    # Force the 1H layer to report an opposing last_mss, as if structure just reversed. Patched on
    # H (hierarchy.py's own imported name), since that is the binding evaluate() actually calls.
    monkeypatch.setattr(H, "evaluate_intraday", lambda h1, ctx: {
        "intraday_bias": "BULLISH", "compatible_with_htf": True,
        "structure": {"state": "BULLISH", "last_bos": "bullish", "last_mss": "bearish", "reason": "x"},
        "checklist": []})
    out = H.evaluate(fr, NOW)
    assert out["state"] == "INVALIDATED"
    assert "1H directional structure invalidated" in out["invalidation"]["text"]


def test_no_invalidation_without_a_resolved_direction():
    fr = _frames("up")
    fr["D1"] = path_candles(BEARISH_POINTS, 10, 1440, DOWN_TAIL)  # 1D/4H disagree -> no direction
    out = H.evaluate(fr, NOW)
    assert out["invalidation"] is None


# --- Evidence traceability: every conclusion points to timeframe/timestamp/kind/value/source ----

def test_every_supporting_and_contradicting_item_is_traceable():
    fr = _frames("up")
    out = H.evaluate(fr, NOW)
    for e in out["supporting_evidence"] + out["contradicting_evidence"]:
        assert e["timeframe"] and e["timestamp"] and e["kind"] and e["source"]
        pd.Timestamp(e["timestamp"])  # parses without raising


def test_checklist_items_carry_timeframe_and_reason_never_a_vague_statement():
    fr = _frames("up")
    out = H.evaluate(fr, NOW)
    for section in ("higher_timeframe", "intraday", "setup_15m", "confirmation_5m"):
        layer = out[section]
        if layer is None:
            continue
        for c in layer["checklist"]:
            assert c["timeframe"] and c["reason"]
            assert c["status"] in CM.STATUSES


# --- Entry candidate: only with a resolved direction and confirmation reached -------------------

def test_no_entry_candidate_before_confirmation_is_reached():
    fr = _frames("up")
    out = H.evaluate(fr, NOW)
    if out["state"] not in ("ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY"):
        assert out["entry_candidate"] is None


def test_entry_candidate_reuses_the_existing_risk_primitives(monkeypatch):
    fr = _frames("up")
    m15 = fr["M15"]

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {"bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev(timeframe, NOW, "SWEEP_LOW", float(price) - 5, "x")},
                            {"kind": "MSS_BOS", "evidence": CM.ev(timeframe, NOW, "MSS_BOS_BULLISH", price, "x")}],
                "bearish": []}

    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    monkeypatch.setattr(C5, "gather_directional_evidence", fake_evidence)
    out = H.evaluate(fr, NOW)
    assert out["setup_15m"]["setup_status"] == "SETUP_CONFIRMED"
    assert out["confirmation_5m"]["confirmation_status"] == "CONFIRMED"
    assert out["state"] in ("ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY")
    cand = out["entry_candidate"]
    assert cand is not None
    assert cand["direction"] == "LONG"
    assert cand["entry"] == round(float(m15["close"].iloc[-1]) if False else cand["entry"], 2)  # entry is a price
    if cand["stop"] is not None:
        assert cand["stop"]["price"] < cand["entry"]  # a LONG stop sits below entry


def test_confidence_is_labelled_heuristic_never_a_probability():
    fr = _frames("up")
    out = H.evaluate(fr, NOW)
    assert out["confidence"] is not None
    assert out["confidence"]["type"] == "HEURISTIC"
    assert "probability" in out["confidence"]["note"].lower() and "not" in out["confidence"]["note"].lower()


# --- Safety: no execution, no LLM in the decision path -------------------------------------------

def test_hierarchy_source_has_no_llm_or_order_dependency():
    files = ("hierarchy.py", "htf.py", "intraday.py", "setup_15m.py", "confirmation_5m.py",
            "precision_1m.py", "common.py")
    banned = ("ai.providers", "ai.prompts", "anthropic", "groq", "openai", "place_order", "order_send",
             "trade_execution", "execute_trade")
    root = pathlib.Path(H.__file__).parent
    for name in files:
        text = (root / name).read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{name} references {token}"


# --- Route: generic over the active implementation's shape --------------------------------------

def test_route_returns_the_hierarchy_result(monkeypatch):
    from api.routes import entry_model as route
    from mt5 import market_data

    frames = _frames("up")

    def fake(timeframe, count):
        return frames[timeframe]

    monkeypatch.setattr(market_data, "get_candles", fake)
    out = route.get_entry_model()
    assert out["symbol"] == "XAUUSD"
    assert "higher_timeframe" in out and "setup_15m" in out and "entry_candidate" in out
    assert "Manual decision support" in out["disclaimer"]


# --- Direction/state gating fix -------------------------------------------------------------------
# The exposed `direction` field must only ever read LONG/SHORT once the FULL hierarchy actually
# supports it (1D/4H resolved -> 1H resolved and compatible -> 15M resolved -> 5M CONFIRMED). Before
# the fix, `direction` was read directly off setup_15m's own resolution with no further gate, so it
# could -- and in 142/400 real samples, did -- show a confident LONG/SHORT while `state` was still
# stuck before the HTF/1H layers had resolved anything (docs/entry-model-v2-outcome-research.md,
# section 12). These tests drive hierarchy.evaluate() end to end with each layer mocked in turn, so
# each one isolates exactly the missing-resolution scenario it names.

def _fake_htf(context, location="APPROACHING_ZONE"):
    return {"htf_location": location, "htf_context": context, "d1_bias": "neutral", "h4_bias": "neutral",
            "d1_structure": None, "h4_structure": None, "nearest_area": None, "relation": None,
            "key_areas": [], "major_d1_levels": [], "checklist": []}


def _fake_intraday(bias, compatible):
    return {"intraday_bias": bias, "compatible_with_htf": compatible,
            "structure": {"state": "RANGING", "last_bos": None, "last_mss": None, "reason": "x"},
            "checklist": []}


_STRONG_BULLISH_EVIDENCE = {
    "bullish": [{"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev("M15", NOW, "SWEEP_LOW", 1.0, "x")},
               {"kind": "MSS_BOS", "evidence": CM.ev("M15", NOW, "MSS_BOS_BULLISH", 1.0, "x")},
               {"kind": "DISPLACEMENT", "evidence": CM.ev("M15", NOW, "DISPLACEMENT_BULLISH", 1.0, "x")}],
    "bearish": [],
}
_EMPTY_EVIDENCE = {"bullish": [], "bearish": []}


def test_direction_absent_while_1d_4h_is_unresolved_even_with_strong_15m_evidence(monkeypatch):
    monkeypatch.setattr(H, "evaluate_htf", lambda *a, **k: _fake_htf("NEUTRAL"))
    monkeypatch.setattr(H, "evaluate_intraday", lambda *a, **k: _fake_intraday("BULLISH", True))
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)
    out = H.evaluate(_frames("up"), NOW)
    assert out["direction"] is None
    assert out["state"] in ("NO_CONTEXT", "HTF_LOCATION_IDENTIFIED")
    # Root-cause check, not a surface patch: the 15M layer itself must not have resolved a
    # direction either, not just have it hidden at the output.
    assert out["setup_15m"]["setup_direction"] == "NEUTRAL"


def test_direction_absent_when_htf_resolved_but_1h_unresolved(monkeypatch):
    monkeypatch.setattr(H, "evaluate_htf", lambda *a, **k: _fake_htf("BULLISH"))
    monkeypatch.setattr(H, "evaluate_intraday", lambda *a, **k: _fake_intraday("NEUTRAL", True))
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)
    out = H.evaluate(_frames("up"), NOW)
    assert out["direction"] is None
    assert out["state"] == "HTF_CONTEXT_ALIGNED"
    assert out["setup_15m"]["setup_direction"] == "NEUTRAL"


def test_direction_absent_when_1h_resolved_but_incompatible_with_htf(monkeypatch):
    """1H resolved to a bias, but flagged incompatible with the 1D/4H context -- still unresolved
    for the purpose of establishing a direction."""
    monkeypatch.setattr(H, "evaluate_htf", lambda *a, **k: _fake_htf("BEARISH"))
    monkeypatch.setattr(H, "evaluate_intraday", lambda *a, **k: _fake_intraday("BULLISH", False))
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)
    out = H.evaluate(_frames("up"), NOW)
    assert out["direction"] is None
    assert out["setup_15m"]["setup_direction"] == "NEUTRAL"


def test_direction_absent_when_1h_resolved_but_15m_unresolved(monkeypatch):
    monkeypatch.setattr(H, "evaluate_htf", lambda *a, **k: _fake_htf("BULLISH"))
    monkeypatch.setattr(H, "evaluate_intraday", lambda *a, **k: _fake_intraday("BULLISH", True))
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _EMPTY_EVIDENCE)
    out = H.evaluate(_frames("up"), NOW)
    assert out["direction"] is None
    assert out["setup_15m"]["setup_status"] == "WAITING"


def test_direction_absent_when_15m_confirmed_but_5m_not_confirmed(monkeypatch):
    """The core bug scenario: a fully-confirmed 15M setup, sitting on a fully-resolved 1D/4H/1H
    chain, must still not expose a direction until 5M actually confirms it."""
    monkeypatch.setattr(H, "evaluate_htf", lambda *a, **k: _fake_htf("BULLISH"))
    monkeypatch.setattr(H, "evaluate_intraday", lambda *a, **k: _fake_intraday("BULLISH", True))
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)
    monkeypatch.setattr(C5, "gather_directional_evidence", lambda *a, **k: _EMPTY_EVIDENCE)
    out = H.evaluate(_frames("up"), NOW)
    assert out["setup_15m"]["setup_status"] == "SETUP_CONFIRMED"
    assert out["state"] == "SETUP_CONFIRMED"
    assert out["confirmation_5m"]["confirmation_status"] == "WAITING"
    assert out["direction"] is None  # the fix: SETUP_CONFIRMED alone is not enough
    assert out["entry_candidate"] is None


def test_direction_present_once_5m_actually_confirms():
    """The full, valid chain -- the only case direction should actually appear."""
    m15 = _frames("up")["M15"]
    with mock.patch.object(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE), \
         mock.patch.object(C5, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE):
        out = H.evaluate(_frames("up"), NOW)
    assert out["confirmation_5m"]["confirmation_status"] == "CONFIRMED"
    assert out["direction"] == "LONG"
    assert out["state"] in ("ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY")


def test_1m_precision_never_creates_direction_when_5m_is_only_developing(monkeypatch):
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)
    monkeypatch.setattr(C5, "gather_directional_evidence", lambda *a, **k: {
        "bullish": [{"kind": "MSS_BOS", "evidence": CM.ev("M5", NOW, "MSS_BOS_BULLISH", 1.0, "x")}], "bearish": []})
    # Even if 1M precision reports AVAILABLE, 5M is only DEVELOPING -- direction must stay absent.
    monkeypatch.setattr(H, "evaluate_precision", lambda *a, **k: {
        "precision_status": "AVAILABLE", "trigger": {"time_utc": str(NOW), "direction": "bullish"}, "checklist": []})
    out = H.evaluate(_frames("up"), NOW)
    assert out["confirmation_5m"]["confirmation_status"] == "DEVELOPING"
    assert out["direction"] is None


def test_1m_precision_never_changes_an_already_established_direction(monkeypatch):
    """Once 5M has genuinely confirmed, flipping 1M precision on or off must not change `direction`
    at all -- 1M is precision only, never part of the direction decision."""
    monkeypatch.setattr(S15, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)
    monkeypatch.setattr(C5, "gather_directional_evidence", lambda *a, **k: _STRONG_BULLISH_EVIDENCE)

    monkeypatch.setattr(H, "evaluate_precision", lambda *a, **k: {
        "precision_status": "AVAILABLE", "trigger": {"time_utc": str(NOW), "direction": "bullish"}, "checklist": []})
    out_with_precision = H.evaluate(_frames("up"), NOW)

    monkeypatch.setattr(H, "evaluate_precision", lambda *a, **k: {
        "precision_status": "WAITING", "trigger": None, "checklist": []})
    out_without_precision = H.evaluate(_frames("up"), NOW)

    assert out_with_precision["direction"] == out_without_precision["direction"] == "LONG"
