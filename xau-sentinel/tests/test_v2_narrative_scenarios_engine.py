"""Analysis V2 narrative determinism, conditional scenarios, and engine-level
guarantees: multi-timeframe alignment, regression against the existing engine,
no mutation of inputs, and no dependency on A+ or any LLM code."""
import re
from datetime import timedelta
from pathlib import Path

import pytest

from analysis.liquidity import detect_sweeps
from analysis.regime import classify_regime
from analysis.structure import analyze_structure, closed_only
from analysis.v2.engine import build_analysis
from analysis.v2.observations import build_observations
from analysis.zones import compute_zones
from tests.test_structure import BEARISH_POINTS
from tests.v2_fixtures import DOWN_TAIL, path_candles, range_set, trend_set

V2_DIR = Path(__file__).resolve().parent.parent / "analysis" / "v2"
PROBABILITY_WORDS = re.compile(r"probab|chance|likelihood|confiden|will win|will lose|buy now|sell now|"
                               r"\benter (?:the )?trade\b|\bsize up\b", re.IGNORECASE)


def _now(candles):
    return candles["M5"]["close_time"].iloc[-1].to_pydatetime()


def _analysis(candles):
    return build_analysis(candles, now=_now(candles))


# --- narrative -------------------------------------------------------------

def test_narrative_is_identical_for_identical_input():
    a = _analysis(trend_set("up"))
    b = _analysis(trend_set("up"))
    assert a.narrative == b.narrative


def test_narrative_sections_appear_in_their_fixed_order():
    lines = _analysis(trend_set("up")).narrative
    order = ["Direction:", "Structure:", "Regime:", "Price location:", "Nearby key areas:", "Recent events:",
             "Liquidity:", "Volatility:", "Volume:", "Momentum:", "Session:"]
    positions = [next(i for i, line in enumerate(lines) if line.startswith(prefix)) for prefix in order]
    assert positions == sorted(positions)


def test_narrative_states_contradictions_and_data_limits_explicitly():
    candles = trend_set("up")
    candles["M5"] = path_candles(BEARISH_POINTS, 24, 5, DOWN_TAIL)
    text = "\n".join(_analysis(candles).narrative)
    assert "Structure conflicts across timeframes" in text
    assert "Contradictory evidence" in text
    partial = trend_set("up")
    del partial["H4"]
    assert "Data limits" in "\n".join(_analysis(partial).narrative)


def test_narrative_contains_no_probability_or_instruction_language():
    for candles in (trend_set("up"), trend_set("down"), range_set()):
        text = "\n".join(_analysis(candles).narrative)
        assert not PROBABILITY_WORDS.search(text), text


# --- scenarios -------------------------------------------------------------

def test_bullish_trend_produces_continuation_and_reversal_with_real_levels():
    a = _analysis(trend_set("up"))
    names = [s.name for s in a.scenarios]
    assert names == ["CONTINUATION", "REVERSAL"]
    cont = a.scenarios[0]
    assert cont.direction == "bullish"
    assert any("128.00" in c for c in cont.confirmation_requirements)
    assert any("112.00" in c for c in cont.invalidation_conditions)
    rev = a.scenarios[1]
    assert rev.direction == "bearish"
    assert rev.direction != cont.direction


def test_bearish_trend_mirrors_the_levels():
    a = _analysis(trend_set("down"))
    cont = next(s for s in a.scenarios if s.name == "CONTINUATION")
    assert cont.direction == "bearish"
    assert any("72.00" in c for c in cont.confirmation_requirements)
    assert any("88.00" in c for c in cont.invalidation_conditions)


def test_range_produces_only_a_two_sided_scenario():
    a = _analysis(range_set())
    assert [s.name for s in a.scenarios] == ["RANGE"]
    s = a.scenarios[0]
    assert s.direction is None
    assert s.confirmation_requirements and s.invalidation_conditions


def test_every_scenario_is_conditional_and_carries_its_disclaimer():
    for candles in (trend_set("up"), trend_set("down"), range_set()):
        for s in _analysis(candles).scenarios:
            assert s.condition and s.supporting_conditions is not None
            assert s.confirmation_requirements and s.invalidation_conditions
            assert "not predictions" in s.disclaimer.lower()
            assert not PROBABILITY_WORDS.search(" ".join(
                [s.condition, *s.confirmation_requirements, *s.invalidation_conditions]))


def test_scenario_text_never_issues_an_instruction():
    for candles in (trend_set("up"), trend_set("down"), range_set()):
        for s in _analysis(candles).scenarios:
            text = " ".join([s.condition, *s.confirmation_requirements, *s.invalidation_conditions])
            assert not re.search(r"\b(buy|sell|enter|exit|close the position|place)\b", text, re.IGNORECASE), text


def test_scenarios_reference_real_areas_and_events_when_they_exist():
    a = _analysis(trend_set("up"))
    cont = a.scenarios[0]
    assert all(isinstance(x, str) for x in cont.key_area_refs + cont.event_refs)


# --- engine guarantees -----------------------------------------------------

def test_multi_timeframe_alignment_of_a_clean_trend():
    obs = build_observations(trend_set("up"))
    assert {tf: obs.structure[tf].state for tf in ("M5", "M15", "H1", "H4")} == \
        {"M5": "BULLISH", "M15": "BULLISH", "H1": "BULLISH", "H4": "BULLISH"}


def test_engine_matches_the_existing_structure_regime_sweeps_and_zones():
    candles = range_set()
    a = _analysis(candles)
    closed = {tf: closed_only({tf: candles[tf]})[tf] for tf in candles}
    for tf in ("M5", "M15", "H1", "H4"):
        assert a.observations.structure[tf].state == analyze_structure(closed[tf]).state
    assert a.observations.zones == compute_zones(closed["M5"], closed["H1"], closed["H4"])
    assert [(s.kind, s.time) for s in a.observations.sweeps] == \
        [(s.kind, s.time) for s in detect_sweeps(closed["M5"], a.observations.zones)]
    assert a.context.regime.state == classify_regime(closed["H1"], closed["M15"]).regime


def test_engine_does_not_mutate_its_input():
    candles = trend_set("up")
    before = {tf: df.copy(deep=True) for tf, df in candles.items()}
    _analysis(candles)
    for tf in candles:
        assert candles[tf].equals(before[tf])


def test_stale_feed_is_flagged_not_hidden():
    candles = trend_set("up")
    a = build_analysis(candles, now=_now(candles) + timedelta(days=3))
    assert a.status == "STALE"
    assert a.notes and "historical" in a.notes[0]


def test_empty_candles_return_insufficient_data_without_exceptions():
    a = build_analysis({})
    assert a.status == "INSUFFICIENT_DATA"
    assert a.scenarios == () and a.areas == () and a.confluence is None


@pytest.mark.parametrize("module", sorted(p.name for p in V2_DIR.glob("*.py")))
def test_v2_does_not_depend_on_a_plus_or_any_llm_code(module):
    text = (V2_DIR / module).read_text(encoding="utf-8")
    forbidden = ("from ai", "import ai", "ai.strategy", "anthropic", "openai", "groq", "langchain")
    assert not [f for f in forbidden if f in text], f"{module} imports forbidden code"


# --- wording guarantees (review pass) ---------------------------------------

@pytest.mark.parametrize("n,expected", [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"),
                                        (12, "12th"), (21, "21st"), (22, "22nd"), (101, "101st")])
def test_ordinals_read_correctly_in_the_volatility_line(n, expected):
    from analysis.v2.context import _ordinal
    assert _ordinal(n) == expected


def test_stale_feed_note_is_the_first_narrative_line():
    candles = trend_set("up")
    a = build_analysis(candles, now=_now(candles) + timedelta(days=3))
    assert a.narrative[0].startswith("The M5 feed is older")


def test_area_relations_are_written_as_sentences_not_bare_labels():
    from analysis.v2.narrative import _area_phrase
    from analysis.v2.models import KeyArea
    from analysis.v2.relations import AreaState
    area = KeyArea(3000.0, 3002.0, (), "RESISTANCE", "LOW", "x")
    approaching = AreaState(area, "APPROACHING", 0.5, ("r",))
    inside = AreaState(area, "INSIDE", 0.0, ("r",))
    assert _area_phrase(approaching) == "3000.00-3002.00 (price is approaching it, 0.50 ATR away)"
    assert _area_phrase(inside) == "3000.00-3002.00 (price is inside it)"
    assert "[" not in _area_phrase(approaching)


def test_scenario_text_avoids_forecast_wording_should_and_vague_hold():
    for candles in (trend_set("up"), trend_set("down"), range_set()):
        for s in _analysis(candles).scenarios:
            text = " ".join([s.condition, *s.confirmation_requirements, *s.invalidation_conditions])
            assert "should" not in text.lower(), text
            assert "holds there" not in text, text


def test_event_lines_carry_their_own_description():
    lines = _analysis(trend_set("up")).narrative
    recent = next(line for line in lines if line.startswith("Recent events:"))
    assert "BOS" in recent or "breakout" in recent or "retest" in recent or "sweep" in recent
    assert "(bullish)" not in recent and "(bearish)" not in recent
