"""Analysis V2 context dimensions and confluence/contradictions. There must be no
combined score anywhere, and volume must never count as a direction."""
import dataclasses
from analysis.liquidity import LiquidityEvent
from analysis.v2.confluence import Confluence
from analysis.v2.context import Dimension, MarketContext, build_context
from analysis.v2.engine import build_analysis
from analysis.v2.observations import build_observations
from analysis.structure import closed_only
from tests.v2_fixtures import DOWN_TAIL, path_candles, range_set, trend_set
from tests.test_structure import BEARISH_POINTS


def _now(candles):
    return candles["M5"]["close_time"].iloc[-1].to_pydatetime()


def _closed(candles):
    return {tf: closed_only({tf: df})[tf] for tf, df in candles.items()}


def _context(candles):
    obs = build_observations(candles)
    closed = _closed(candles)
    a = build_analysis(candles, now=_now(candles))
    return obs, build_context(obs, closed, a.events), a


def test_context_dimensions_are_independent_fields_with_no_combined_score():
    fields = {f.name for f in dataclasses.fields(MarketContext)}
    assert not fields & {"score", "confidence", "grade", "probability", "total"}
    _, ctx, _ = _context(trend_set("up"))
    for name in ("direction", "regime", "volatility", "volume", "liquidity", "momentum", "session", "price_location"):
        assert isinstance(getattr(ctx, name), Dimension)
    assert all(isinstance(v, Dimension) for v in ctx.structure.values())


def test_direction_follows_the_h1_trend_and_is_none_in_a_range():
    _, up, _ = _context(trend_set("up"))
    _, down, _ = _context(trend_set("down"))
    _, flat, _ = _context(range_set())
    assert up.direction.state == "UP"
    assert down.direction.state == "DOWN"
    assert flat.direction.state == "NONE"


def test_volatility_state_combines_percentile_and_ratio_with_explicit_labels():
    obs, _, _ = _context(trend_set("up"))
    high_exp = dataclasses.replace(obs, atr_percentile_m5=90.0, atr_change_m5=1.6)
    low_con = dataclasses.replace(obs, atr_percentile_m5=10.0, atr_change_m5=0.5)
    unknown = dataclasses.replace(obs, atr_percentile_m5=None, atr_change_m5=None)
    closed = _closed(trend_set("up"))
    assert build_context(high_exp, closed, []).volatility.state == "HIGH_EXPANDING"
    assert build_context(low_con, closed, []).volatility.state == "LOW_CONTRACTING"
    assert build_context(unknown, closed, []).volatility.state == "UNKNOWN"


def test_price_location_names_the_previous_day_break_when_it_happens():
    obs, _, _ = _context(trend_set("up"))
    above = dataclasses.replace(obs, current_price=200.0, zones={"Previous Day High": 150.0,
                                                                  "Previous Day Low": 100.0})
    below = dataclasses.replace(obs, current_price=50.0, zones={"Previous Day High": 150.0,
                                                                 "Previous Day Low": 100.0})
    middle = dataclasses.replace(obs, current_price=125.0, zones={"Previous Day High": 150.0,
                                                                   "Previous Day Low": 100.0,
                                                                   "Current Day High": 130.0,
                                                                   "Current Day Low": 120.0})
    closed = _closed(trend_set("up"))
    assert build_context(above, closed, []).price_location.state == "ABOVE_PREVIOUS_DAY_HIGH"
    assert build_context(below, closed, []).price_location.state == "BELOW_PREVIOUS_DAY_LOW"
    assert build_context(middle, closed, []).price_location.state == "MIDDLE_THIRD"


def test_liquidity_state_reflects_which_side_was_swept():
    obs, _, _ = _context(trend_set("up"))
    low_only = dataclasses.replace(obs, sweeps=(LiquidityEvent(obs.as_of, "x swept", "x", 1.0, "sweep_low"),))
    high_low = dataclasses.replace(low_only, sweeps=(
        LiquidityEvent(obs.as_of, "x swept", "x", 1.0, "sweep_low"),
        LiquidityEvent(obs.as_of, "y swept", "y", 2.0, "sweep_high")))
    closed = _closed(trend_set("up"))
    assert build_context(low_only, closed, []).liquidity.state == "SWEPT_LOW"
    assert build_context(high_low, closed, []).liquidity.state == "SWEPT_BOTH_SIDES"
    assert build_context(dataclasses.replace(obs, sweeps=()), closed, []).liquidity.state == "NO_RECENT_SWEEP"


def test_volume_state_is_passed_through_and_labelled_as_activity_only():
    _, ctx, _ = _context(trend_set("up"))
    assert ctx.volume.state in {"EXPANSION", "CONTRACTION", "NORMAL", "UNKNOWN"}
    assert "activity proxy" in ctx.volume.detail


def test_volume_never_counts_as_a_directional_lean():
    candles = trend_set("up")
    obs, ctx, analysis = _context(candles)
    volume_leans = [l for l in analysis.confluence.bullish + analysis.confluence.bearish + analysis.confluence.neutral
                    if "volume" in l.source.lower()]
    assert volume_leans and all(l.lean == "neutral" for l in volume_leans)
    assert all("volume" not in l.source.lower() for l in analysis.confluence.supporting)
    assert all("volume" not in l.source.lower() for l in analysis.confluence.contradicting)


def test_clean_uptrend_has_its_structure_as_support_and_no_structural_contradiction():
    _, _, analysis = _context(trend_set("up"))
    c = analysis.confluence
    assert c.reference == "bullish"
    assert any(l.source == "H1 structure" for l in c.supporting)
    assert not [l for l in c.contradicting if "structure" in l.source]
    assert c.cross_timeframe_conflicts == ()


def test_contradicting_m5_structure_is_listed_and_named_as_a_cross_timeframe_conflict():
    candles = trend_set("up")
    candles["M5"] = path_candles(BEARISH_POINTS, 24, 5, DOWN_TAIL)
    _, _, analysis = _context(candles)
    c = analysis.confluence
    assert c.reference == "bullish"
    assert any(l.source == "M5 structure" for l in c.contradicting)
    assert any("H1 BULLISH vs M5 BEARISH" in x or "M5 BEARISH" in x for x in c.cross_timeframe_conflicts)


def test_no_reference_direction_means_no_supporting_or_contradicting_lists():
    _, _, analysis = _context(range_set())
    c = analysis.confluence
    assert c.reference is None
    assert c.supporting == () and c.contradicting == ()
    assert "No clear trend" in c.reference_reason


def test_confluence_contains_no_numeric_score_fields():
    fields = {f.name for f in dataclasses.fields(Confluence)}
    assert not fields & {"score", "confidence", "weight", "percent", "probability"}
