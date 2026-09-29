"""Tests for ai/trade_review/rules.py — every alignment dimension
(aligned/partially/not/unknown), every well-evidenced deviation fires on
real evidence and stays silent otherwise, the 5 schema-limited deviation
types never fire on any constructed input, outcome is independent of
alignment, and no lookahead (a review built from stored fields never
depends on anything outside the trade dict itself)."""
import inspect

import config
from ai.trade_review import rules
from ai.trade_review.models import DeviationType, Outcome, StrategyAlignment


def _trade(**overrides):
    defaults = dict(
        id=1, status="CLOSED", result="WIN", direction="BUY",
        h1_bias="BULLISH", liquidity="Previous Day Low swept", mss="Bullish", displacement="Bullish",
        planned_rr=3.0, r_multiple=3.0, duration_minutes=45,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Setup alignment
# ---------------------------------------------------------------------------

def test_setup_alignment_aligned_when_all_four_dimensions_consistent():
    assert rules.classify_setup_alignment(_trade()) == StrategyAlignment.ALIGNED


def test_setup_alignment_not_aligned_when_any_dimension_contradicts():
    trade = _trade(h1_bias="BEARISH")
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.NOT_ALIGNED


def test_setup_alignment_partially_aligned_when_some_dimensions_unknown():
    trade = _trade(liquidity=None, mss=None)
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.PARTIALLY_ALIGNED


def test_setup_alignment_unknown_when_nothing_captured():
    trade = _trade(h1_bias=None, liquidity=None, mss=None, displacement=None)
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.UNKNOWN


def test_setup_alignment_handles_sell_direction():
    trade = _trade(direction="SELL", h1_bias="BEARISH", liquidity="Previous Day High swept",
                    mss="Bearish", displacement="Bearish")
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.ALIGNED


def test_setup_alignment_normalizes_casing_for_title_cased_mss_displacement():
    """api/routes/journal.py stores mss/displacement Title Case while
    h1_bias is UPPERCASE — this must not silently misclassify either."""
    trade = _trade(h1_bias="PULLBACK", mss="bullish", displacement="BULLISH")
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.ALIGNED


# ---------------------------------------------------------------------------
# Execution alignment
# ---------------------------------------------------------------------------

def test_execution_alignment_aligned_when_rr_meets_minimum():
    assert rules.classify_execution_alignment(_trade(planned_rr=config.AI_STRATEGY_MIN_RR)) == StrategyAlignment.ALIGNED


def test_execution_alignment_not_aligned_when_rr_below_minimum():
    trade = _trade(planned_rr=config.AI_STRATEGY_MIN_RR - 0.5)
    assert rules.classify_execution_alignment(trade) == StrategyAlignment.NOT_ALIGNED


def test_execution_alignment_unknown_when_rr_missing():
    assert rules.classify_execution_alignment(_trade(planned_rr=None)) == StrategyAlignment.UNKNOWN


# ---------------------------------------------------------------------------
# Risk alignment — uses the trade's OWN immutable snapshot only
# ---------------------------------------------------------------------------

def test_risk_alignment_aligned_when_safe():
    assert rules.classify_risk_alignment({"data_available": True, "safety_level": "SAFE"}) == StrategyAlignment.ALIGNED


def test_risk_alignment_partially_aligned_when_warning():
    assert rules.classify_risk_alignment({"data_available": True, "safety_level": "WARNING"}) == StrategyAlignment.PARTIALLY_ALIGNED


def test_risk_alignment_not_aligned_when_critical_or_breached():
    assert rules.classify_risk_alignment({"data_available": True, "safety_level": "CRITICAL"}) == StrategyAlignment.NOT_ALIGNED
    assert rules.classify_risk_alignment({"data_available": True, "safety_level": "BREACHED"}) == StrategyAlignment.NOT_ALIGNED


def test_risk_alignment_unknown_when_no_snapshot():
    assert rules.classify_risk_alignment(None) == StrategyAlignment.UNKNOWN


def test_risk_alignment_unknown_when_snapshot_not_data_available():
    assert rules.classify_risk_alignment({"data_available": False}) == StrategyAlignment.UNKNOWN


# ---------------------------------------------------------------------------
# Strategy alignment rollup — the worse of setup/execution
# ---------------------------------------------------------------------------

def test_strategy_alignment_is_the_worse_of_setup_and_execution():
    assert rules.classify_strategy_alignment(StrategyAlignment.ALIGNED, StrategyAlignment.NOT_ALIGNED) == StrategyAlignment.NOT_ALIGNED
    assert rules.classify_strategy_alignment(StrategyAlignment.PARTIALLY_ALIGNED, StrategyAlignment.ALIGNED) == StrategyAlignment.PARTIALLY_ALIGNED
    assert rules.classify_strategy_alignment(StrategyAlignment.ALIGNED, StrategyAlignment.ALIGNED) == StrategyAlignment.ALIGNED


# ---------------------------------------------------------------------------
# Outcome — structurally independent of alignment
# ---------------------------------------------------------------------------

def test_outcome_win_loss_breakeven_open_unknown():
    assert rules.classify_outcome(_trade(status="CLOSED", result="WIN")) == Outcome.WIN
    assert rules.classify_outcome(_trade(status="CLOSED", result="LOSS")) == Outcome.LOSS
    assert rules.classify_outcome(_trade(status="CLOSED", result="BE")) == Outcome.BREAKEVEN
    assert rules.classify_outcome(_trade(status="OPEN", result=None)) == Outcome.OPEN
    assert rules.classify_outcome(_trade(status="CLOSED", result=None)) == Outcome.UNKNOWN


def test_a_loss_can_be_fully_aligned():
    """The spec's own explicit example: Outcome=LOSS, strategy_alignment=ALIGNED is completely valid."""
    trade = _trade(result="LOSS")
    assert rules.classify_outcome(trade) == Outcome.LOSS
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.ALIGNED


def test_a_win_can_be_not_aligned():
    trade = _trade(result="WIN", h1_bias="BEARISH")
    assert rules.classify_outcome(trade) == Outcome.WIN
    assert rules.classify_setup_alignment(trade) == StrategyAlignment.NOT_ALIGNED


def test_classify_outcome_never_reads_alignment_fields():
    """Structural: outcome classification must never even look at the
    technical/execution fields — proven by checking its source never
    mentions them."""
    source = inspect.getsource(rules.classify_outcome)
    for banned in ("h1_bias", "liquidity", "mss", "displacement", "planned_rr", "safety_level"):
        assert banned not in source


# ---------------------------------------------------------------------------
# Deviations — well-evidenced ones fire correctly
# ---------------------------------------------------------------------------

def test_no_deviations_for_a_fully_aligned_trade():
    assert rules.detect_deviations(_trade(), {"data_available": True, "safety_level": "SAFE"}) == []


def test_direction_deviation_fires_on_contradicting_h1_bias():
    devs = rules.detect_deviations(_trade(h1_bias="BEARISH"), None)
    assert any(d.type == DeviationType.DIRECTION_DEVIATION for d in devs)


def test_missed_confirmation_fires_when_mss_missing_but_liquidity_present():
    devs = rules.detect_deviations(_trade(mss=None), None)
    assert any(d.type == DeviationType.MISSED_CONFIRMATION for d in devs)


def test_missed_confirmation_fires_when_mss_contradicts_direction():
    devs = rules.detect_deviations(_trade(mss="Bearish"), None)
    assert any(d.type == DeviationType.MISSED_CONFIRMATION for d in devs)


def test_missing_context_fires_when_nothing_captured():
    trade = _trade(h1_bias=None, liquidity=None, mss=None, displacement=None)
    devs = rules.detect_deviations(trade, None)
    assert any(d.type == DeviationType.MISSING_CONTEXT for d in devs)
    # nothing else should fire when there's no context to evaluate against
    assert not any(d.type == DeviationType.DIRECTION_DEVIATION for d in devs)


def test_outside_strategy_fires_when_two_or_more_dimensions_contradict():
    trade = _trade(h1_bias="BEARISH", mss="Bearish")
    devs = rules.detect_deviations(trade, None)
    assert any(d.type == DeviationType.OUTSIDE_STRATEGY for d in devs)


def test_outside_strategy_does_not_fire_for_a_single_contradiction():
    trade = _trade(h1_bias="BEARISH")
    devs = rules.detect_deviations(trade, None)
    assert not any(d.type == DeviationType.OUTSIDE_STRATEGY for d in devs)


def test_insufficient_rr_fires_below_minimum():
    devs = rules.detect_deviations(_trade(planned_rr=1.0), None)
    assert any(d.type == DeviationType.INSUFFICIENT_RR for d in devs)


def test_insufficient_rr_does_not_fire_when_rr_missing():
    devs = rules.detect_deviations(_trade(planned_rr=None), None)
    assert not any(d.type == DeviationType.INSUFFICIENT_RR for d in devs)


def test_risk_limit_deviation_fires_when_not_safe():
    devs = rules.detect_deviations(_trade(), {"data_available": True, "safety_level": "CRITICAL"})
    assert any(d.type == DeviationType.RISK_LIMIT_DEVIATION for d in devs)


def test_risk_limit_deviation_does_not_fire_when_safe_or_unavailable():
    assert not any(d.type == DeviationType.RISK_LIMIT_DEVIATION
                   for d in rules.detect_deviations(_trade(), {"data_available": True, "safety_level": "SAFE"}))
    assert not any(d.type == DeviationType.RISK_LIMIT_DEVIATION
                   for d in rules.detect_deviations(_trade(), None))


# ---------------------------------------------------------------------------
# Schema-limited deviations — defined, but never fire (honest limitation)
# ---------------------------------------------------------------------------

_NEVER_FIRE = (
    DeviationType.EARLY_ENTRY, DeviationType.LATE_ENTRY, DeviationType.SL_DEVIATION,
    DeviationType.TP_DEVIATION, DeviationType.INVALIDATED_SETUP_TRADED,
)


def test_schema_limited_deviations_never_fire_on_any_constructed_input():
    scenarios = [
        _trade(), _trade(h1_bias="BEARISH"), _trade(planned_rr=0.5),
        _trade(h1_bias=None, liquidity=None, mss=None, displacement=None),
        _trade(result="LOSS", planned_rr=1.0, h1_bias="BEARISH", mss="Bearish"),
    ]
    snapshots = [None, {"data_available": True, "safety_level": "BREACHED"}]
    for trade in scenarios:
        for snapshot in snapshots:
            devs = rules.detect_deviations(trade, snapshot)
            fired_types = {d.type for d in devs}
            assert not fired_types & set(_NEVER_FIRE)


# ---------------------------------------------------------------------------
# No lookahead — a review depends only on the trade dict given, nothing external
# ---------------------------------------------------------------------------

def _source_without_module_docstring(module) -> str:
    """Strips the module's own docstring by AST line range before a
    substring search — the docstring explains this file's no-lookahead
    guarantee in prose using the same function names being searched for,
    which would otherwise false-positive a plain source-text search on
    itself (the same fix used for ai/monitoring/engine.py's equivalent
    test in Stage 13)."""
    import ast
    source = inspect.getsource(module)
    tree = ast.parse(source)
    lines = source.splitlines()
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
        node = tree.body[0]
        lines = lines[:node.lineno - 1] + lines[node.end_lineno:]
    return "\n".join(lines)


def test_rules_module_never_calls_live_market_or_account_functions():
    import ai.trade_review.rules as rules_mod
    code = _source_without_module_docstring(rules_mod)
    for banned in ("get_all_candles", "compute_status(", "build_snapshot", "detect_setup("):
        assert banned not in code
