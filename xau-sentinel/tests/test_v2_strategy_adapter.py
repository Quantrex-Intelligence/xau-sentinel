"""Analysis V2 -> A+ adapter: field mapping, stale and insufficient data, missing and
conflicting evidence, determinism, equivalence with the legacy path, and the rule
that the adapter never recomputes market facts or decides a rating itself."""
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from ai.strategy import evaluator as evaluator_mod
from ai.v2_strategy import bridge as v2_bridge
from ai.v2_strategy.comparison import compare_paths
from ai.strategy.evaluator import collect_legacy_facts, decide_from_facts
from ai.v2_strategy.bridge import V2NotEvaluable, facts_from_v2
from analysis.structure import analyze_structure, closed_only
from analysis.liquidity import detect_sweeps
from analysis.v2.engine import build_analysis
from analysis.zones import compute_zones
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel
from tests.v2_fixtures import path_candles, range_set, trend_set, with_forming_bar, DOWN_TAIL
from tests.test_structure import BEARISH_POINTS

FN_SAFE = FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                           data_available=True, safety_level=SafetyLevel.SAFE, daily_loss_used_pct=10.0)


def _now(candles):
    return candles["M5"]["close_time"].iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)


def _v2(candles, now=None):
    return build_analysis(candles, now=now or _now(candles))


# --- field mapping -----------------------------------------------------------

def test_structure_mapping_matches_the_legacy_engine_for_every_timeframe():
    candles = trend_set("up")
    facts = facts_from_v2(_v2(candles), candles)
    legacy = collect_legacy_facts(candles, _now(candles))
    for name in ("h4", "h1", "m15", "m5"):
        v2_s, legacy_s = getattr(facts, name), getattr(legacy, name)
        assert (v2_s.state, v2_s.reason, v2_s.last_mss, v2_s.last_bos) == \
               (legacy_s.state, legacy_s.reason, legacy_s.last_mss, legacy_s.last_bos), name


def test_h1_bias_mapping_drives_the_same_h1_gate_as_the_legacy_path():
    candles = trend_set("up")
    facts = facts_from_v2(_v2(candles), candles)
    assert facts.h1.state == "BULLISH"
    assert facts.h1.last_mss is None  # V2 reports the same structure state A+ reads, unchanged


def test_liquidity_and_zone_mapping_are_identical_to_the_legacy_detection():
    for candles in (trend_set("up"), trend_set("down"), range_set()):
        facts = facts_from_v2(_v2(candles), candles)
        closed = closed_only(candles)
        zones = compute_zones(closed["M5"], closed["H1"], closed["H4"])
        assert facts.zones == zones
        assert [(s.kind, s.level_name, s.time) for s in facts.sweeps] == \
               [(s.kind, s.level_name, s.time) for s in detect_sweeps(closed["M5"], zones)]


def test_freshness_mapping_follows_the_same_staleness_rule():
    candles = trend_set("up")
    fresh = facts_from_v2(_v2(candles), candles)
    stale = facts_from_v2(_v2(candles, now=_now(candles) + timedelta(days=3)), candles)
    assert fresh.data_stale is False
    assert stale.data_stale is True


def test_entry_price_keeps_the_a_plus_forming_bar_semantics_not_v2s_closed_price():
    base = trend_set("up")
    candles = with_forming_bar(base, "M5", close=4200.0)
    analysis = _v2(base)
    facts = facts_from_v2(analysis, candles)
    assert facts.current_price == float(candles["M5"]["close"].iloc[-1])  # A+ entry semantics
    assert analysis.observations.current_price == float(closed_only({"M5": base["M5"]})["M5"]["close"].iloc[-1])
    assert facts.current_price != analysis.observations.current_price


# --- stale, insufficient, missing evidence --------------------------------------

def test_stale_v2_data_never_rates_a_plus_through_the_adapter():
    candles = trend_set("up")
    stale_now = _now(candles) + timedelta(days=3)
    facts = facts_from_v2(_v2(candles, now=stale_now), candles)
    ev = decide_from_facts(facts, FN_SAFE, stale_now)
    assert ev.rating.value != "A+"
    assert facts.data_stale is True


def test_insufficient_v2_data_is_reported_not_guessed():
    from datetime import datetime
    empty_now = datetime(2026, 1, 5, tzinfo=timezone.utc)
    with pytest.raises(V2NotEvaluable):
        facts_from_v2(build_analysis({}, now=empty_now), {})
    short = trend_set("up")
    short["M5"] = short["M5"].iloc[:40]
    with pytest.raises(V2NotEvaluable):
        facts_from_v2(_v2(short), short)


def test_compare_reports_not_evaluable_instead_of_a_rating_when_v2_has_no_data():
    candles = trend_set("up")
    short = dict(candles)
    short["M5"] = candles["M5"].iloc[:40]
    result = compare_paths(short, FN_SAFE, _now(candles))
    assert result["v2_status"] == "not_evaluable"
    assert "v2_evaluation" not in result
    assert result["legacy_evaluation"]["rating"] in {"A+", "DEVELOPING", "INVALID"}


def test_missing_h4_is_marked_insufficient_and_does_not_change_the_a_plus_gates():
    candles = trend_set("up")
    del candles["H4"]
    analysis = _v2(candles)
    facts = facts_from_v2(analysis, candles)
    assert facts.h4.state == "INSUFFICIENT"
    # H4 is context only in the A+ rules, so the gate outcome is unchanged by its absence.
    full = trend_set("up")
    ev_missing = decide_from_facts(facts, FN_SAFE, _now(full))
    ev_full = decide_from_facts(facts_from_v2(_v2(full), full), FN_SAFE, _now(full))
    assert [(c.name, c.status) for c in ev_missing.criteria if c.name != "Liquidity Sweep"] == \
           [(c.name, c.status) for c in ev_full.criteria if c.name != "Liquidity Sweep"]


# --- conflicting evidence ------------------------------------------------------------

def test_conflicting_timeframes_keep_each_timeframes_own_state():
    candles = trend_set("up")
    candles["M5"] = path_candles(BEARISH_POINTS, 24, 5, DOWN_TAIL)
    facts = facts_from_v2(_v2(candles), candles)
    assert facts.h1.state == "BULLISH"
    assert facts.m5.state == "BEARISH"
    result = compare_paths(candles, FN_SAFE, _now(candles))
    assert result["agreement"]["rating"] is True  # both paths see the same conflict and decide the same way


# --- determinism and equivalence ----------------------------------------------------

def test_adapter_output_is_deterministic():
    candles = trend_set("up")
    now = _now(candles)
    a = compare_paths(candles, FN_SAFE, now)
    b = compare_paths(candles, FN_SAFE, now)
    assert a == b


@pytest.mark.parametrize("make", [lambda: trend_set("up"), lambda: trend_set("down"), range_set])
def test_v2_path_and_legacy_path_give_identical_evaluations_when_v2_provides_the_same_facts(make):
    candles = make()
    now = _now(candles)
    legacy = evaluator_mod.evaluate_deterministic(candles, FN_SAFE, now=now).model_dump(exclude={"evaluated_at"})
    v2 = decide_from_facts(facts_from_v2(_v2(candles, now=now), candles), FN_SAFE, now).model_dump(exclude={"evaluated_at"})
    assert v2 == legacy


def test_no_sequence_mss_is_reported_when_there_is_no_sweep_candidate():
    candles = range_set()
    result = compare_paths(candles, FN_SAFE, _now(candles))
    if not result["legacy_inputs"]["sweeps"]:
        assert result["mss_semantics"] == {"legacy": None, "v2": None}


# --- the adapter never recomputes facts or decides a rating -----------------------------

def test_adapter_module_does_not_recompute_any_market_fact():
    source = Path(v2_bridge.__file__).read_text(encoding="utf-8")
    for forbidden in ("analyze_structure(", "detect_sweeps(", "compute_zones(", "detect_equal_levels(",
                      "compute_atr(", "evaluate_sequence(", "decide_from_facts(", "evaluate_deterministic("):
        assert forbidden not in source, forbidden


def test_adapter_module_cannot_produce_a_trade_direction_or_rating():
    source = Path(v2_bridge.__file__).read_text(encoding="utf-8")
    assert "Rating." not in source
    assert '"BUY"' not in source and '"SELL"' not in source


def test_comparison_output_contains_no_probability_or_score_terms():
    import json, re
    result = compare_paths(trend_set("up"), FN_SAFE, _now(trend_set("up")))
    text = json.dumps(result, default=str)
    assert not re.search(r"probab|confiden|\bscore\b|\bBUY\b|\bSELL\b", text, re.IGNORECASE)
